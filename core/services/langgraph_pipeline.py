import os
from typing import Dict, List, TypedDict, Tuple
from urllib.parse import urlparse
from langgraph.graph import StateGraph, START, END
from django.conf import settings
from core.services.openrouter import OpenRouterLLM
from core.services.rag_client import RAGClient, RAGClientError
from core.models import ChatSession, ChatMessage
from asgiref.sync import sync_to_async
from django.utils import timezone

MAX_HISTORY = int(os.getenv("CHAT_MAX_HISTORY", "8"))
TOP_K = int(os.getenv("RAG_TOP_K", "5"))
TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))
MODEL = os.getenv("OPENROUTER_MODEL", "openrouter/auto")

SYSTEM_PROMPT = """You are a friendly and intelligent assistant for students and members of Sharif University of Technology. Your name is "Sharif Study Buddy" and your goal is to help users quickly and accurately access university information.

**CRITICAL: ALWAYS RESPOND IN PERSIAN (FARSI).** All your responses must be in Persian, regardless of the language of the question or context. This is non-negotiable.

## Your Role and Personality:
- You are a friendly, helpful, and professional assistant who is always ready to help
- You speak in a friendly, respectful, and warm tone (like a knowledgeable friend)
- You use academic terminology but always explain it
- You are patient and try to answer questions in the best possible way
- **Always respond in Persian (Farsi) - this is mandatory**

## Response Guidelines:

### 1. Using Contextual Information:
- Always first review the information retrieved from university documents
- If relevant information exists in the context, definitely use it
- Quote information accurately and without distortion
- If multiple relevant sources exist, consider all of them and integrate them

### 2. Your Areas of Expertise:
- Education and courses: curriculum, prerequisites, credits, professors
- Academic calendar: important dates, registration, exams, holidays
- Regulations: educational, disciplinary, graduation rules
- Dormitory: conditions, registration, rules
- Food and restaurants: menu, service hours, reservations
- Library: working hours, services, borrowing rules
- Administrative systems: usage, registration, common issues
- Research and graduate studies: research opportunities, scholarships, programs

### 3. Response Structure:
- Start with a friendly greeting (e.g., "سلام! بله، خوشحالم که می‌تونم کمکت کنم...")
- Present the main answer clearly and in a structured way
- Use bullet points or numbering for complex information
- Provide practical examples when needed
- End with an offer for further help (e.g., "اگه سؤال دیگه‌ای داری، بپرس!")
- **Remember: All responses must be in Persian**

### 4. Managing Uncertainty:
- If there isn't enough information in the context, honestly say: "متأسفانه اطلاعات دقیقی در این مورد در اسناد موجود نیست، ولی..."
- Suggest where the user can find information (e.g., "بهتره با واحد آموزش تماس بگیری")
- If information is outdated, mention its date
- If there are multiple possibilities, mention all of them

### 5. Sources and Citations:
- **Only cite a source if you have directly used information from it in your answer.** If no sources from the context are used, do not include a "Sources" (منابع) section at all.
- In the context, each document includes "📄 عنوان:" (actual document title), "📝 محتوا:" (content), and "🔗 منبع:" (URL).
- **Very important:** Always use the actual title from "📄 عنوان:" (not the URL, not the content text, nothing else).
- At the end of your response, if you used sources, include them in HTML link format so they're clickable in Telegram.
- Correct format for Telegram links:
  <a href="Full URL">Actual document title from 📄 عنوان:</a>
- Example: If the context shows:
  📄 عنوان: آیین‌نامه استفاده از ابزار هوش مصنوعی
  🔗 منبع: https://ac.sharif.edu/rules/ai-ethics
  You should write:
  📚 منابع:
  <a href="https://ac.sharif.edu/rules/ai-ethics">آیین‌نامه استفاده از ابزار هوش مصنوعی</a>
- If you used multiple sources, list them all in order
- If the source is "سند داخلی دانشگاه" (internal university document), only mention the document title without a link
- Always use HTML format for links (not plain text)

### 6. Topics Outside Your Domain:
- If the question is unrelated to Sharif University, say in a friendly way:
  "این سؤال خارج از حوزه دانشگاه شریف است، ولی می‌تونم یک پاسخ کلی بدم..."
- Then provide a useful and general answer
- Always specify that this information is not from university documents

### 7. Clarification:
- If the question is ambiguous, ask in a friendly way: "می‌تونی کمی بیشتر توضیح بدی؟"
- Try to break down the question into smaller questions
- If you need more information, ask

### 8. Tone and Style:
- Use "تو" (informal "you") for friendliness (not "شما" which is more formal)
- Use emojis sparingly and appropriately (e.g., ✅, 📚, 🎓)
- Short and clear sentences
- Use real and understandable examples
- Avoid complex technical terms without explanation
- **All responses must be in Persian (Farsi)**

### 9. Limitations:
- Only respond based on information available in the context
- Avoid speculation
- If you don't know, say you don't know
- Always be honest and transparent

## Example of a Good Response:
"سلام! بله، خوشحالم که می‌تونم کمکت کنم 😊

بر اساس آیین‌نامه دانشگاه، استفاده از ابزارهای هوش مصنوعی در تکالیف و امتحانات باید با اجازه استاد باشد. برای جزئیات بیشتر می‌تونی به بخش آیین‌نامه آموزشی مراجعه کنی.

اگه سؤال دیگه‌ای داری، بپرس!"

---
**Important Reminder:** Always first review the context and respond based on it. If the context is empty or insufficient, honestly say so and guide the user on where they can find the information.

**LANGUAGE REQUIREMENT:** You MUST respond in Persian (Farsi) at all times. This is not optional."""


class GraphState(TypedDict):
    question: str
    history: List[Dict[str, str]]
    context: str
    answer: str
    debug: Dict


async def _history(session: ChatSession) -> List[Dict[str, str]]:
    messages = await sync_to_async(list)(
        session.messages.order_by("created_at").values("role", "content")
    )
    return messages[-MAX_HISTORY:] if len(messages) > MAX_HISTORY else messages


async def _save(session: ChatSession, role: str, content: str) -> None:
    msg = ChatMessage(session=session, role=role,
                      content=content, created_at=timezone.now())
    await sync_to_async(msg.save)()


async def retrieve_node(state: GraphState) -> GraphState:
    rag = RAGClient()
    snippets: List[str] = []
    debug = {"rag": {}}
    try:
        # user_id is handled inside RAGClient (default fixed ID for now)
        res = await rag.search(query=state["question"], top_k=TOP_K)
        debug["rag"] = res
        items = res.get("results") or res.get("data") or []

        for idx, it in enumerate(items[:TOP_K], 1):
            text = it.get("text") or it.get("chunk") or it.get("content") or ""
            if not text.strip():
                continue

            # Extract metadata for better source display
            metadata = it.get("metadata") or {}
            title = (
                it.get("title")
                or metadata.get("title")
                or metadata.get("file_name")
                or metadata.get("name")
            )
            source_url = (
                it.get("url")
                or metadata.get("url")
                or metadata.get("source_url")
            )
            source_name = it.get("source") or metadata.get(
                "source") or metadata.get("knowledge_source")
            file_name = it.get("file_name") or metadata.get("file_name")
            file_path = it.get("file_path") or metadata.get("file_path")
            page = it.get("page") or metadata.get("page")
            score = it.get("score") or metadata.get("score")
            owner_user_id = it.get(
                "owner_user_id") or metadata.get("owner_user_id")

            # Build a structured snippet with source information
            snippet_parts = []

            # Title
            if title:
                snippet_parts.append(f"📄 عنوان: {title}")

            # Source name
            if source_name:
                snippet_parts.append(f"🏷️ منبع دانش: {source_name}")

            # File info
            file_info_bits = []
            if file_name:
                file_info_bits.append(f"نام فایل: {file_name}")
            if file_path:
                file_info_bits.append(f"مسیر: {file_path}")
            if page:
                file_info_bits.append(f"صفحه: {page}")
            if file_info_bits:
                snippet_parts.append("📁 " + " | ".join(file_info_bits))

            # Score (rounded)
            if score is not None:
                try:
                    snippet_parts.append(f"⭐ امتیاز: {float(score):.3f}")
                except Exception:
                    snippet_parts.append(f"⭐ امتیاز: {score}")

            # Owner info (optional)
            if owner_user_id:
                snippet_parts.append(f"👤 مالک سند: {owner_user_id}")

            # Content
            snippet_parts.append(f"📝 محتوا:\n{text}")

            # URL
            if source_url:
                # Store full URL in context (we'll format it for display in post-processing)
                snippet_parts.append(f"🔗 منبع: {source_url}")
            else:
                snippet_parts.append("🔗 منبع: سند داخلی دانشگاه")

            snippets.append("\n".join(snippet_parts))

    except RAGClientError as e:
        snippets.append(f"⚠️ هشدار: سرویس RAG در دسترس نبود: {e}")

    # Format context with clear separation between documents
    if snippets:
        context = "\n\n" + "=" * 50 + "\n\n".join(
            [f"📚 سند {idx}:\n{snippet}" for idx,
                snippet in enumerate(snippets, 1)]
        ) + "\n\n" + "=" * 50
    else:
        context = "⚠️ هیچ سند مرتبطی یافت نشد."

    state["context"] = context
    state.setdefault("debug", {}).update(debug)
    return state


async def generate_node(state: GraphState) -> GraphState:
    api_key = settings.OPENROUTER_API_KEY or os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured")

    llm = OpenRouterLLM(
        api_key=api_key,
        model=MODEL,
        temperature=TEMPERATURE,
        streaming=False,
    )

    messages: List[Dict[str, str]] = []

    # Build context section with clear formatting
    context = state.get("context", "")
    context_section = ""
    if context and context != "⚠️ هیچ سند مرتبطی یافت نشد.":
        context_section = f"""
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📚 اطلاعات بازیابی‌شده از اسناد دانشگاه:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{context}

**Instructions for Using Sources:**
- Use the information above to provide an accurate answer to the user's question
- If multiple relevant documents exist, consider all of them
- At the end of your response, cite the sources used in HTML link format
- **Important:** Always use the actual document title from "📄 عنوان:" field (not the URL or other text)
- Correct format:
  📚 منابع:
  <a href="Full URL">Actual document title</a>
- Example: If the context shows "📄 عنوان: آیین‌نامه استفاده از ابزار هوش مصنوعی" and "🔗 منبع: https://ac.sharif.edu/rules/ai-ethics"
  You should write: <a href="https://ac.sharif.edu/rules/ai-ethics">آیین‌نامه استفاده از ابزار هوش مصنوعی</a>
- Always use the HTML tag <a href="...">...</a> so links are clickable in Telegram
- **CRITICAL: All your responses, including source citations, must be in Persian (Farsi)**
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    else:
        context_section = "\n⚠️ No relevant documents were found in the knowledge base. In this case, if you have general information, respond while noting that this information is not from university documents.\n**Remember: Always respond in Persian (Farsi).**\n"

    messages.append({
        "role": "system",
        "content": SYSTEM_PROMPT + context_section
    })
    messages.extend(state.get("history", []))
    messages.append({"role": "user", "content": state["question"]})
    response = await llm.ainvoke(messages)
    answer = response.content

    # Post-process: Convert source references to clickable HTML links if not already formatted
    answer = _convert_sources_to_html_links(answer, state.get("context", ""))

    state["answer"] = answer
    return state


def _convert_sources_to_html_links(answer: str, context: str) -> str:
    """
    Convert source references in the answer to HTML links for Telegram.
    If LLM didn't format sources correctly, extract from context and convert.
    Always uses the actual document title from metadata.
    """
    import re

    # Check if answer already has properly formatted HTML links with sources section
    if '<a href=' in answer and '📚 منابع:' in answer:
        # Verify links are properly formatted, if yes, return as is
        if re.search(r'<a href="https?://[^"]+">[^<]+</a>', answer):
            return answer

    # Extract URLs and titles from context by parsing document structure
    # Pattern: 📚 سند X: ... 📄 عنوان: TITLE ... 🔗 منبع: URL
    sources = []

    # Split context by document separators
    doc_sections = re.split(r'📚 سند \d+:', context)

    for section in doc_sections:
        if not section.strip():
            continue

        # Extract title (this is the actual document title from metadata)
        title_match = re.search(r'📄 عنوان:\s*([^\n]+)', section)
        title = title_match.group(1).strip() if title_match else None

        # Extract URL
        url_match = re.search(r'🔗 منبع:\s*(https?://[^\s\n]+)', section)
        url = url_match.group(1).strip() if url_match else None

        # Only add if we have both URL and title
        if url and title:
            sources.append((url, title))
        elif url:
            # If no title, try to extract from URL or use URL
            parsed = urlparse(url)
            # Try to create a readable title from URL path
            path_parts = [p for p in parsed.path.split('/') if p]
            if path_parts:
                # Use last meaningful part
                fallback_title = path_parts[-1].replace(
                    '-', ' ').replace('_', ' ')
                fallback_title = ' '.join(word.capitalize()
                                          for word in fallback_title.split())
            else:
                fallback_title = parsed.netloc.replace('www.', '')
            sources.append((url, fallback_title))

    # If no sources found, return answer as is
    if not sources:
        return answer

    # Remove any existing source section (text or partial HTML) to replace with formatted version
    # Remove text-based source sections
    answer = re.sub(r'\n\n?📚 منابع?:?\s*\n.*?(?=\n\n|\Z)',
                    '', answer, flags=re.DOTALL)
    # Remove markdown-style source references at the end
    answer = re.sub(r'\n\n?\[منبع[^\]]+\]\s*$', '', answer, flags=re.MULTILINE)

    # Replace any inline text source references with HTML links
    source_ref_pattern = r'\[منبع\s*\d*:\s*([^\]]+)\]'

    def replace_source(match):
        source_text = match.group(1).strip()
        # Try to match with our extracted sources
        for url, title in sources:
            # Check if URL or title appears in source_text
            if url in source_text or (title and title.lower() in source_text.lower()):
                return f'<a href="{url}">{title}</a>'
        # If no match, return original
        return match.group(0)

    answer = re.sub(source_ref_pattern, replace_source, answer)

    # Add a formatted source list at the end only if the LLM's answer contains references.
    # This respects the LLM's decision on which sources are relevant.
    has_references = re.search(
        source_ref_pattern, answer) or re.search(r'📚 منابع:', answer)

    if has_references:
        # Ensure a clean slate by removing any partial/text-based source list
        answer = re.sub(r'\n\n?📚 منابع?:?.*', '', answer, flags=re.DOTALL)

        # Build the HTML source list
        sources_html = '\n\n📚 منابع:\n' + '\n'.join([
            f'<a href="{url}">{title}</a>' for url, title in sources
        ])
        answer = answer.rstrip() + sources_html

    # Final cleanup of any remaining empty reference tags
    answer = re.sub(r'\[منبع\s*\d*:\[^\]]*\]', '', answer).strip()

    return answer


async def run_graph(session: ChatSession, user_text: str) -> Tuple[str, Dict]:
    await _save(session, "user", user_text)
    state: GraphState = {
        "question": user_text,
        "history": await _history(session),
        "context": "",
        "answer": "",
        "debug": {},
    }
    graph = StateGraph(GraphState)
    graph.add_node("retrieve", retrieve_node)
    graph.add_node("generate", generate_node)
    graph.add_edge(START, "retrieve")
    graph.add_edge("retrieve", "generate")
    graph.add_edge("generate", END)
    app = graph.compile()
    final: GraphState = await app.ainvoke(state)
    answer = final.get("answer", "")
    await _save(session, "assistant", answer)
    return answer, final.get("debug", {})

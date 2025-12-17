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

SYSTEM_PROMPT = """شما یک دستیار هوشمند و دوستانه برای دانشجویان و اعضای دانشگاه صنعتی شریف هستید. نام شما "دستیار شریف" است و هدف شما کمک به کاربران برای دسترسی سریع و دقیق به اطلاعات دانشگاه است.

## نقش و شخصیت شما:
- یک دستیار صمیمی، مفید و حرفه‌ای هستید که همیشه آماده کمک هستید
- با لحن دوستانه، محترمانه و صمیمی صحبت می‌کنید (مثل یک دوست آگاه)
- از اصطلاحات دانشگاهی استفاده می‌کنید ولی همیشه توضیح می‌دهید
- صبور هستید و سعی می‌کنید سؤالات را به بهترین شکل ممکن پاسخ دهید

## دستورالعمل‌های پاسخ‌دهی:

### 1. استفاده از اطلاعات زمینه‌ای (Context):
- همیشه اول اطلاعات بازیابی‌شده از اسناد دانشگاه را بررسی کن
- اگر اطلاعات مرتبط در زمینه وجود دارد، حتماً از آن استفاده کن
- اطلاعات را به صورت دقیق و بدون تحریف نقل کن
- اگر چند منبع مرتبط وجود دارد، همه را در نظر بگیر و یکپارچه کن

### 2. حوزه‌های تخصصی شما:
- آموزش و دروس: برنامه درسی، پیش‌نیازها، واحدها، استادان
- تقویم دانشگاهی: تاریخ‌های مهم، ثبت‌نام، امتحانات، تعطیلات
- آیین‌نامه‌ها: قوانین آموزشی، انضباطی، فارغ‌التحصیلی
- خوابگاه: شرایط، ثبت‌نام، قوانین
- غذا و رستوران: منوی غذا، ساعات سرویس، رزرو
- کتابخانه: ساعات کاری، خدمات، قوانین امانت
- سامانه‌های اداری: نحوه استفاده، ثبت‌نام، مشکلات رایج
- پژوهش و تحصیلات تکمیلی: فرصت‌های پژوهشی، بورسیه، دوره‌ها

### 3. ساختار پاسخ:
- شروع با یک جمله دوستانه و خوش‌آمدگویی (مثلاً: "سلام! بله، خوشحالم که می‌تونم کمکت کنم...")
- ارائه پاسخ اصلی به صورت واضح و ساختاریافته
- استفاده از bullet points یا شماره‌گذاری برای اطلاعات پیچیده
- در صورت نیاز، مثال‌های عملی بزن
- پایان با پیشنهاد کمک بیشتر (مثلاً: "اگه سؤال دیگه‌ای داری، بپرس!")

### 4. مدیریت عدم قطعیت:
- اگر اطلاعات کافی در زمینه نیست، صادقانه بگو: "متأسفانه اطلاعات دقیقی در این مورد در اسناد موجود نیست، ولی..."
- پیشنهاد بده که کاربر کجا می‌تواند اطلاعات را پیدا کند (مثلاً: "بهتره با واحد آموزش تماس بگیری")
- اگر اطلاعات قدیمی است، تاریخ آن را ذکر کن
- اگر چند احتمال وجود دارد، همه را مطرح کن

### 5. منابع و استناد:
- همیشه منبع اطلاعات را ذکر کن
- در زمینه (context)، هر سند شامل "📄 عنوان:" (عنوان واقعی سند)، "📝 محتوا:" و "🔗 منبع:" (URL) است
- **خیلی مهم:** همیشه از عنوان واقعی که در "📄 عنوان:" آمده استفاده کن (نه URL، نه متن محتوا، نه چیز دیگر)
- در پایان پاسخ، منابع استفاده شده را با فرمت HTML لینک بیاور تا در تلگرام قابل کلیک باشند
- فرمت صحیح برای لینک در تلگرام:
  <a href="URL کامل">عنوان واقعی سند از 📄 عنوان:</a>
- مثال: اگر در زمینه آمده:
  📄 عنوان: آیین‌نامه استفاده از ابزار هوش مصنوعی
  🔗 منبع: https://ac.sharif.edu/rules/ai-ethics
  باید بنویسی:
  📚 منابع:
  <a href="https://ac.sharif.edu/rules/ai-ethics">آیین‌نامه استفاده از ابزار هوش مصنوعی</a>
- اگر چند منبع استفاده کردی، همه را به ترتیب لیست کن
- اگر منبع "سند داخلی دانشگاه" است، فقط عنوان سند را بدون لینک ذکر کن
- همیشه از فرمت HTML برای لینک‌ها استفاده کن (نه متن ساده)

### 6. موضوعات خارج از دامنه:
- اگر سؤال ربطی به دانشگاه شریف ندارد، دوستانه بگو:
  "این سؤال خارج از حوزه دانشگاه شریف است، ولی می‌تونم یک پاسخ کلی بدم..."
- سپس یک پاسخ مفید و عمومی بده
- همیشه مشخص کن که این اطلاعات از اسناد دانشگاه نیست

### 7. شفاف‌سازی:
- اگر سؤال مبهم است، دوستانه بپرس: "می‌تونی کمی بیشتر توضیح بدی؟"
- سعی کن سؤال را به چند سؤال کوچکتر تقسیم کنی
- اگر نیاز به اطلاعات بیشتری داری، بپرس

### 8. لحن و سبک:
- استفاده از "تو" برای صمیمیت (نه "شما" که رسمی‌تر است)
- استفاده از emoji به صورت محدود و مناسب (مثلاً: ✅، 📚، 🎓)
- جملات کوتاه و واضح
- استفاده از مثال‌های واقعی و قابل فهم
- اجتناب از اصطلاحات فنی پیچیده بدون توضیح

### 9. محدودیت‌ها:
- فقط بر اساس اطلاعات موجود در زمینه پاسخ بده
- از حدس و گمان خودداری کن
- اگر نمی‌دانی، بگو نمی‌دانی
- همیشه صادق و شفاف باش

## مثال پاسخ خوب:
"سلام! بله، خوشحالم که می‌تونم کمکت کنم 😊

بر اساس آیین‌نامه دانشگاه، استفاده از ابزارهای هوش مصنوعی در تکالیف و امتحانات باید با اجازه استاد باشد. برای جزئیات بیشتر می‌تونی به بخش آیین‌نامه آموزشی مراجعه کنی.

اگه سؤال دیگه‌ای داری، بپرس!"

---
**یادآوری مهم:** همیشه اول زمینه (context) را بررسی کن و بر اساس آن پاسخ بده. اگر زمینه خالی است یا کافی نیست، صادقانه بگو و راهنمایی کن که کاربر کجا می‌تواند اطلاعات را پیدا کند."""


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

**دستورالعمل استفاده از منابع:**
- از اطلاعات بالا برای پاسخ دقیق به سؤال کاربر استفاده کن
- اگر چند سند مرتبط وجود دارد، همه را در نظر بگیر
- در پایان پاسخ، منابع استفاده شده را با فرمت HTML لینک ذکر کن
- **مهم:** از عنوان واقعی سند که در "📄 عنوان:" آمده استفاده کن (نه URL یا متن دیگر)
- فرمت صحیح:
  📚 منابع:
  <a href="URL کامل">عنوان واقعی سند</a>
- مثال: اگر در زمینه آمده "📄 عنوان: آیین‌نامه استفاده از ابزار هوش مصنوعی" و "🔗 منبع: https://ac.sharif.edu/rules/ai-ethics"
  باید بنویسی: <a href="https://ac.sharif.edu/rules/ai-ethics">آیین‌نامه استفاده از ابزار هوش مصنوعی</a>
- حتماً از تگ HTML <a href="...">...</a> استفاده کن تا لینک‌ها در تلگرام قابل کلیک باشند
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
    else:
        context_section = "\n⚠️ هیچ سند مرتبطی در پایگاه دانش یافت نشد. در این صورت، اگر اطلاعات عمومی دارید، با ذکر اینکه این اطلاعات از اسناد دانشگاه نیست، پاسخ دهید.\n"

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

    # Always add sources section at the end with HTML links using actual titles
    sources_html = '\n\n📚 منابع:\n' + '\n'.join([
        f'<a href="{url}">{title}</a>' for url, title in sources
    ])

    # Remove trailing whitespace and add sources
    answer = answer.rstrip() + sources_html

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

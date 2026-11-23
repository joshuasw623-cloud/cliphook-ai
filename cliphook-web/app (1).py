import html
import json
import re

import streamlit as st
import streamlit.components.v1 as components
from google import genai
from google.genai import types
from youtube_transcript_api import YouTubeTranscriptApi

# ----------------------------------------------------------------------------
# Konfigurasi halaman
# ----------------------------------------------------------------------------
st.set_page_config(
    page_title="ClipHook AI",
    page_icon="🎬",
    layout="wide",
    initial_sidebar_state="collapsed",
)

CUSTOM_CSS = """
<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap');

html, body, [class*="css"], .stApp { font-family: 'Inter', sans-serif; }
.stApp { background: radial-gradient(1200px 600px at 10% -10%, #1e1b4b 0%, #0b0b14 55%) fixed; }
#MainMenu, footer, header { visibility: hidden; }
.block-container { padding-top: 2rem; max-width: 1100px; }

.hero { text-align: center; padding: 1.5rem 0 1rem; }
.hero h1 {
    font-size: 3rem; font-weight: 800; margin: 0; letter-spacing: -1px;
    background: linear-gradient(90deg, #a78bfa, #60a5fa, #34d399);
    -webkit-background-clip: text; -webkit-text-fill-color: transparent;
}
.hero p { color: #9ca3af; font-size: 1.05rem; margin-top: .4rem; }
.badge {
    display: inline-block; padding: 3px 12px; border-radius: 999px; font-size: .75rem;
    background: rgba(167,139,250,.15); color: #c4b5fd; border: 1px solid rgba(167,139,250,.35);
    margin-bottom: .8rem; font-weight: 600;
}

.card {
    background: rgba(255,255,255,.04); border: 1px solid rgba(255,255,255,.09);
    border-radius: 16px; padding: 18px 20px; margin-bottom: 10px;
    backdrop-filter: blur(8px);
}
.card .meta { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; margin-bottom: 6px; }
.pill {
    font-size: .75rem; font-weight: 700; padding: 3px 10px; border-radius: 999px;
    background: rgba(96,165,250,.15); color: #93c5fd; border: 1px solid rgba(96,165,250,.3);
    text-decoration: none !important;
}
.pill.score { background: rgba(52,211,153,.15); color: #6ee7b7; border-color: rgba(52,211,153,.3); }
.card h4 { margin: 4px 0 6px; font-size: 1.05rem; color: #f3f4f6; font-weight: 700; }
.card p { margin: 0; color: #cbd5e1; line-height: 1.6; font-size: .95rem; }
.hooktext {
    font-size: 1.5rem; font-weight: 800; color: #fff; line-height: 1.25; text-align: center;
    padding: 6px 0; text-transform: uppercase;
}
.section-title { font-size: 1.35rem; font-weight: 800; color: #f9fafb; margin: 1.8rem 0 .6rem; }
.section-sub { color: #9ca3af; font-size: .9rem; margin-top: -.4rem; margin-bottom: .8rem; }

.stButton > button[kind="primary"] {
    background: linear-gradient(90deg, #7c3aed, #2563eb); border: 0; color: white;
    font-weight: 700; border-radius: 12px; padding: .65rem 1rem; width: 100%;
}
.stButton > button[kind="primary"]:hover { filter: brightness(1.15); }
.stTextInput input, .stTextArea textarea {
    background: rgba(255,255,255,.05) !important; border-radius: 12px !important;
    border: 1px solid rgba(255,255,255,.12) !important; color: #f3f4f6 !important;
}
</style>
"""
st.markdown(CUSTOM_CSS, unsafe_allow_html=True)


# ----------------------------------------------------------------------------
# Helper
# ----------------------------------------------------------------------------
def copy_button(text: str, label: str = "📋 Salin", height: int = 46):
    """Tombol salin (clipboard) berbasis JS, dengan fallback execCommand."""
    payload = json.dumps(text).replace("</", "<\\/")
    page = """
    <style>
      body { margin:0; font-family: Inter, system-ui, sans-serif; }
      button {
        width:100%; height:38px; cursor:pointer; border-radius:10px; font-weight:700;
        font-size:13px; color:#c4b5fd; background:rgba(167,139,250,.12);
        border:1px solid rgba(167,139,250,.4); transition:.15s;
      }
      button:hover { background:rgba(167,139,250,.28); }
      button.ok { color:#6ee7b7; border-color:rgba(52,211,153,.5); background:rgba(52,211,153,.12); }
    </style>
    <button id="b">__LABEL__</button>
    <script>
      const txt = __PAYLOAD__;
      const label = "__LABEL__";
      const btn = document.getElementById('b');
      function fallback() {
        const t = document.createElement('textarea');
        t.value = txt; document.body.appendChild(t); t.select();
        try { document.execCommand('copy'); } catch (e) {}
        document.body.removeChild(t);
      }
      btn.onclick = async () => {
        try { await navigator.clipboard.writeText(txt); } catch (e) { fallback(); }
        btn.textContent = '✅ Tersalin!'; btn.classList.add('ok');
        setTimeout(() => { btn.textContent = label; btn.classList.remove('ok'); }, 1600);
      };
    </script>
    """.replace("__PAYLOAD__", payload).replace("__LABEL__", label)
    components.html(page, height=height)


def extract_video_id(url: str):
    patterns = [
        r"(?:youtu\.be/)([\w-]{11})",
        r"(?:v=)([\w-]{11})",
        r"(?:embed/|shorts/|live/|v/)([\w-]{11})",
    ]
    for p in patterns:
        m = re.search(p, url)
        if m:
            return m.group(1)
    if re.fullmatch(r"[\w-]{11}", url.strip()):
        return url.strip()
    return None


def fmt_time(seconds: float) -> str:
    seconds = int(seconds)
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m:02d}:{s:02d}"


def to_seconds(ts: str) -> int:
    try:
        parts = [int(float(x)) for x in str(ts).strip().split(":")]
    except Exception:
        return 0
    sec = 0
    for p in parts:
        sec = sec * 60 + p
    return sec


@st.cache_data(show_spinner=False, ttl=3600)
def fetch_transcript(video_id: str):
    """Ambil transkrip (prioritas Indonesia lalu Inggris). Return (list_of_dict, bahasa)."""
    api = YouTubeTranscriptApi()
    try:
        fetched = api.fetch(video_id, languages=["id", "en"])
    except Exception as first_err:
        # Fallback: ambil transkrip apa pun yang tersedia
        try:
            tlist = api.list(video_id)
            chosen = next(iter(tlist))
            fetched = chosen.fetch()
        except Exception:
            raise first_err
    items = [
        {"text": s.text, "start": float(s.start), "duration": float(s.duration)}
        for s in fetched
    ]
    return items, getattr(fetched, "language_code", "?")


def parse_manual_transcript(raw: str):
    """Parser transkrip manual. Mendukung beberapa format hasil salinan:
    1) '0.070 detik teks'  (format M.SS + menit diulang, hasil salin dari HP/YouTube versi tertentu)
    2) '[mm:ss] teks' atau '00:12 teks'
    3) timestamp '0:12' di baris sendiri, teks di baris berikutnya (format desktop YouTube)
    4) teks polos tanpa timestamp
    """
    pat_detik = re.compile(r"^(\d+)\.(\d{2})\d*\s*detik\s*(.*)$", re.IGNORECASE)
    pat_clock = re.compile(r"^\[?(\d{1,2}:\d{2}(?::\d{2})?)\]?\s*(.*)$")
    items, last, pending = [], 0.0, None
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        m = pat_detik.match(line)
        if m:
            start = int(m.group(1)) * 60 + int(m.group(2))
            text = m.group(3).strip()
            pending = None
        else:
            m = pat_clock.match(line)
            if m:
                start = to_seconds(m.group(1))
                text = m.group(2).strip()
                if not text:  # timestamp di baris sendiri
                    pending = float(start)
                    continue
                pending = None
            else:
                start = pending if pending is not None else last
                text = line
                pending = None
        if text:
            last = float(start)
            items.append({"text": text, "start": last, "duration": 0.0})
    return items


def build_transcript_text(items, chunk_seconds: int = 12, max_chars: int = 350_000) -> str:
    """Gabungkan potongan pendek jadi baris '[mm:ss] teks' agar hemat token."""
    lines, buf, buf_start = [], [], None
    for it in items:
        if buf_start is None:
            buf_start = it["start"]
        buf.append(it["text"].replace("\n", " ").strip())
        if it["start"] - buf_start >= chunk_seconds:
            lines.append(f"[{fmt_time(buf_start)}] {' '.join(buf)}")
            buf, buf_start = [], None
    if buf:
        lines.append(f"[{fmt_time(buf_start)}] {' '.join(buf)}")
    text = "\n".join(lines)
    return text[:max_chars]


SYSTEM_PROMPT = """Kamu adalah editor video short-form senior dan pakar konten viral TikTok/Instagram Reels/YouTube Shorts
untuk pasar Indonesia. Tugasmu membantu video clipper menemukan momen paling berpotensi viral dari transkrip
video panjang (podcast, wawancara, film, dll) lalu membuat hook yang kuat.

Aturan:
- Gunakan HANYA isi transkrip. Jangan mengarang kejadian atau kutipan.
- Timestamp wajib memakai format MM:SS (atau H:MM:SS jika lebih dari 1 jam) dan harus sesuai transkrip.
- Setiap momen sebaiknya berdurasi 20-75 detik, punya awal dan akhir yang utuh, dan bisa berdiri sendiri.
- Prioritaskan: konflik, pengakuan jujur, plot twist, kontroversi, angka mengejutkan, humor, emosi kuat, tips praktis.
- Hook text: maksimal 8 kata, huruf besar boleh, memicu rasa penasaran, cocok dibaca dalam 3 detik pertama.
- Hook audio: 1-2 kalimat narasi pembuka yang natural untuk direkam ulang clipper (gaya bicara santai, bukan kaku).
- Bahasa output: Bahasa Indonesia gaul-santai yang tetap rapi.
- Output HANYA JSON valid tanpa markdown, sesuai skema berikut:

{
  "ringkasan": "ringkasan video 1-2 kalimat",
  "momen_viral": [
    {"mulai": "MM:SS", "selesai": "MM:SS", "judul": "judul singkat momen", "alasan": "kenapa menarik/viral", "skor_viral": 1-10}
  ],
  "hook_text": ["hook 1", "hook 2", "hook 3"],
  "hook_audio": "kalimat narasi pembuka",
  "judul": ["judul 1", "judul 2", "judul 3"],
  "caption": ["caption lengkap + hashtag 1", "caption lengkap + hashtag 2", "caption lengkap + hashtag 3"]
}

Jumlah: tepat 5 momen_viral (urut dari skor tertinggi), tepat 3 hook_text, tepat 1 hook_audio, 3 judul, 3 caption.
Setiap caption berisi kalimat pembuka menarik, ajakan interaksi (CTA), dan 4-6 hashtag relevan."""


FALLBACK_MODELS = ["gemini-3.8-flash", "gemini-flash-latest"]


def call_gemini(api_key: str, model: str, transcript_text: str, extra: str) -> dict:
    client = genai.Client(api_key=api_key)
    prompt = (
        f"{SYSTEM_PROMPT}\n\nCatatan tambahan dari clipper: {extra or '-'}\n\n"
        f"TRANSKRIP (format [menit:detik] teks):\n{transcript_text}"
    )
    # Coba model pilihan user dulu, lalu model cadangan jika model dihentikan (404)
    candidates = [model] + [m for m in FALLBACK_MODELS if m != model]
    last_err = None
    resp = None
    for m in candidates:
        try:
            resp = client.models.generate_content(
                model=m,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0.8,
                    response_mime_type="application/json",
                ),
            )
            break
        except Exception as e:
            msg = str(e)
            if "404" in msg or "NOT_FOUND" in msg:
                last_err = e
                continue
            raise
    if resp is None:
        raise last_err
    raw = (resp.text or "").strip()
    raw = re.sub(r"^```(?:json)?|```$", "", raw, flags=re.MULTILINE).strip()
    if "{" in raw and "}" in raw:
        raw = raw[raw.index("{"): raw.rindex("}") + 1]
    return json.loads(raw)


def render_card(title: str, body: str, pills_html: str = ""):
    st.markdown(
        f"""<div class="card"><div class="meta">{pills_html}</div>
        <h4>{html.escape(title)}</h4><p>{html.escape(body)}</p></div>""",
        unsafe_allow_html=True,
    )


# ----------------------------------------------------------------------------
# UI
# ----------------------------------------------------------------------------
st.markdown(
    """
    <div class="hero">
      <span class="badge">✨ AI untuk Video Clipper</span>
      <h1>ClipHook AI</h1>
      <p>Temukan momen viral & buat hook yang bikin penonton nggak scroll — dari satu link YouTube.</p>
    </div>
    """,
    unsafe_allow_html=True,
)

default_key = ""
try:
    default_key = st.secrets.get("GEMINI_API_KEY", "")
except Exception:
    pass

with st.container(border=True):
    c1, c2 = st.columns([1, 1.4])
    with c1:
        api_key = st.text_input(
            "🔑 Gemini API Key",
            value=default_key,
            type="password",
            placeholder="AIza...",
            help="Gratis di aistudio.google.com/apikey. Key tidak disimpan oleh aplikasi ini.",
        )
    with c2:
        yt_url = st.text_input("🔗 Link YouTube", placeholder="https://www.youtube.com/watch?v=...")

    with st.expander("⚙️ Pengaturan lanjutan"):
        model_name = st.text_input(
            "Model Gemini",
            value="gemini-3.8-flash",
            help="Jika muncul error 404 (model dihentikan), ganti dengan nama model Flash terbaru dari aistudio.google.com.",
        )
        extra_note = st.text_input(
            "Catatan untuk AI (opsional)",
            placeholder="Contoh: fokus momen lucu, target audiens anak muda, hindari topik politik",
        )
        manual_text = st.text_area(
            "Transkrip manual (opsional, jika pengambilan otomatis gagal)",
            height=140,
            placeholder="[00:12] teks...\n[00:25] teks...\n(salin dari fitur 'Show transcript' di YouTube)",
        )

    go = st.button("🚀 Analisis Video", type="primary")

if go:
    if not api_key:
        st.error("Masukkan Gemini API Key dulu.")
        st.stop()

    items, lang = [], "?"
    vid = extract_video_id(yt_url) if yt_url else None

    if manual_text.strip():
        items = parse_manual_transcript(manual_text)
        lang = "manual"
    elif vid:
        with st.spinner("Mengambil transkrip YouTube..."):
            try:
                items, lang = fetch_transcript(vid)
            except Exception as e:
                msg = str(e)
                if "blocked" in msg.lower() or "ip" in msg.lower():
                    st.error(
                        "YouTube memblokir permintaan dari server ini (umum terjadi di cloud hosting). "
                        "Solusi: tempel transkrip manual di 'Pengaturan lanjutan', atau jalankan aplikasi di lokal."
                    )
                elif "disabled" in msg.lower() or "no transcript" in msg.lower():
                    st.error("Video ini tidak punya transkrip/subtitle yang bisa diambil.")
                else:
                    st.error(f"Gagal mengambil transkrip: {msg[:300]}")
                st.stop()
    else:
        st.error("Link YouTube tidak valid. Contoh: https://www.youtube.com/watch?v=xxxxxxxxxxx")
        st.stop()

    if not items:
        st.error("Transkrip kosong.")
        st.stop()

    transcript_text = build_transcript_text(items)
    st.caption(f"✅ Transkrip diambil ({lang}) • {len(items)} segmen • {len(transcript_text):,} karakter")

    with st.spinner("AI sedang mencari momen viral & menulis hook..."):
        try:
            result = call_gemini(api_key, model_name.strip(), transcript_text, extra_note)
        except json.JSONDecodeError:
            st.error("AI mengembalikan format yang tidak valid. Coba klik Analisis sekali lagi.")
            st.stop()
        except Exception as e:
            msg = str(e)
            if "429" in msg or "quota" in msg.lower():
                st.error("Kuota API gratis habis / terlalu banyak permintaan. Tunggu sebentar lalu coba lagi.")
            elif "404" in msg or "NOT_FOUND" in msg:
                st.error(
                    "Model Gemini tidak ditemukan / sudah dihentikan. Buka 'Pengaturan lanjutan' dan ganti "
                    "nama model dengan Flash terbaru dari aistudio.google.com."
                )
            elif "API key" in msg or "401" in msg or "403" in msg or "400" in msg:
                st.error("API Key tidak valid atau tidak punya akses ke model ini.")
            else:
                st.error(f"Terjadi kesalahan: {msg[:300]}")
            st.stop()

    st.session_state["result"] = result
    st.session_state["vid"] = vid

# ----------------------------------------------------------------------------
# Hasil
# ----------------------------------------------------------------------------
result = st.session_state.get("result")
vid = st.session_state.get("vid")

if result:
    if result.get("ringkasan"):
        st.info(f"📝 **Ringkasan:** {result['ringkasan']}")

    all_text = []

    # 1. Momen viral
    st.markdown('<div class="section-title">🔥 5 Momen Paling Viral</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">Klik timestamp untuk langsung loncat ke momen di YouTube.</div>', unsafe_allow_html=True)
    for i, m in enumerate(result.get("momen_viral", [])[:5], 1):
        mulai, selesai = m.get("mulai", "00:00"), m.get("selesai", "00:00")
        link = f"https://youtu.be/{vid}?t={to_seconds(mulai)}" if vid else "#"
        pills = (
            f'<a class="pill" href="{link}" target="_blank">⏱ {html.escape(str(mulai))} → {html.escape(str(selesai))}</a>'
            f'<span class="pill score">🔥 Skor {html.escape(str(m.get("skor_viral", "-")))}/10</span>'
        )
        col_a, col_b = st.columns([6, 1.2])
        with col_a:
            render_card(f"#{i} {m.get('judul', '')}", m.get("alasan", ""), pills)
        with col_b:
            copy_text = f"{mulai} - {selesai} | {m.get('judul', '')}\nAlasan: {m.get('alasan', '')}"
            copy_button(copy_text)
        all_text.append(f"MOMEN {i}: {copy_text}")

    # 2. Hook text
    st.markdown('<div class="section-title">🅰️ 3 Opsi Hook Text</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">Teks besar untuk layar di 3 detik pertama.</div>', unsafe_allow_html=True)
    for i, h in enumerate(result.get("hook_text", [])[:3], 1):
        col_a, col_b = st.columns([6, 1.2])
        with col_a:
            st.markdown(
                f'<div class="card"><div class="meta"><span class="pill">Opsi {i}</span></div>'
                f'<div class="hooktext">{html.escape(h)}</div></div>',
                unsafe_allow_html=True,
            )
        with col_b:
            copy_button(h)
        all_text.append(f"HOOK TEXT {i}: {h}")

    # 3. Hook audio
    st.markdown('<div class="section-title">🎙️ Hook Audio</div>', unsafe_allow_html=True)
    st.markdown('<div class="section-sub">Narasi pembuka untuk direkam ulang oleh clipper.</div>', unsafe_allow_html=True)
    ha = result.get("hook_audio", "")
    if isinstance(ha, list):
        ha = " ".join(ha)
    col_a, col_b = st.columns([6, 1.2])
    with col_a:
        render_card("Narasi pembuka", ha, '<span class="pill">Voice-over</span>')
    with col_b:
        copy_button(ha)
    all_text.append(f"HOOK AUDIO: {ha}")

    # 4. Judul & caption
    st.markdown('<div class="section-title">✍️ Ide Judul & Caption TikTok/Reels</div>', unsafe_allow_html=True)
    st.markdown("**Judul**")
    for i, t in enumerate(result.get("judul", [])[:3], 1):
        col_a, col_b = st.columns([6, 1.2])
        with col_a:
            render_card(t, "", f'<span class="pill">Judul {i}</span>')
        with col_b:
            copy_button(t)
        all_text.append(f"JUDUL {i}: {t}")

    st.markdown("**Caption**")
    for i, c in enumerate(result.get("caption", [])[:3], 1):
        col_a, col_b = st.columns([6, 1.2])
        with col_a:
            render_card(f"Caption {i}", c, '<span class="pill">Caption</span>')
        with col_b:
            copy_button(c)
        all_text.append(f"CAPTION {i}: {c}")

    st.markdown("---")
    col_a, col_b = st.columns([3, 1.2])
    with col_a:
        st.caption("Salin semua hasil sekaligus:")
    with col_b:
        copy_button("\n\n".join(all_text), label="📋 Salin Semua")

    if vid:
        with st.expander("▶️ Pratinjau video"):
            st.video(f"https://www.youtube.com/watch?v={vid}")

st.markdown(
    "<div style='text-align:center;color:#6b7280;font-size:.8rem;margin-top:2rem'>"
    "ClipHook AI • Dibuat dengan Streamlit & Google Gemini</div>",
    unsafe_allow_html=True,
)

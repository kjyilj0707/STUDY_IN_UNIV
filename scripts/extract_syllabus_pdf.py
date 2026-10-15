"""학교 포털(중앙대) 수업계획서 PDF → 텍스트.

포털 PDF는 한글 폰트를 내장하지 않고 'Adobe-Korea1' CID 폰트(UniKS-UCS2-H)를 쓰며, 글자를 UCS-2(UTF-16BE)로 저장한다.
일반 PDF 도구(pdftotext, pypdf)는 이 문자표가 없어 한글이 깨지므로,
페이지 content stream의 문자열을 직접 꺼내 폰트별로 UTF-16BE / latin-1 로 해석한다.

사용: python scripts/extract_syllabus_pdf.py <입력.pdf> [출력.txt]
"""
import re
import sys

import pypdf

TOKEN = re.compile(
    rb"/(?P<font>[^\s/]+)\s+[\d.]+\s+Tf"          # 폰트 선택
    rb"|(?P<lit>\((?:\\.|[^\\)])*\))"             # (리터럴 문자열)
    rb"|(?P<hex><[0-9A-Fa-f\s]*>)"                # <16진 문자열>
    rb"|(?P<br>\bT[dD*]\b|\bET\b)"                # 줄바꿈 계열 연산자
)
ESC = {ord("n"): b"\n", ord("r"): b"\r", ord("t"): b"\t", ord("b"): b"\b",
       ord("f"): b"\f", ord("("): b"(", ord(")"): b")", 92: bytes([92])}


def literal_bytes(tok: bytes) -> bytes:
    s, out, i = tok[1:-1], bytearray(), 0
    while i < len(s):
        if s[i] == 92 and i + 1 < len(s):  # 백슬래시 이스케이프
            n = s[i + 1]
            if n in ESC:
                out += ESC[n]
                i += 2
            elif 48 <= n <= 55:  # 8진수
                j = i + 1
                while j < len(s) and j < i + 4 and 48 <= s[j] <= 55:
                    j += 1
                out.append(int(s[i + 1:j], 8) & 0xFF)
                i = j
            else:
                i += 2
        else:
            out.append(s[i])
            i += 1
    return bytes(out)


def cjk_font_names(page) -> set:
    """Adobe-Korea1 계열 폰트의 리소스 이름 (예: CJK1, CJK2)."""
    names = set()
    fonts = page.get("/Resources", {}).get("/Font", {})
    for name, ref in fonts.items():
        f = ref.get_object()
        enc = str(f.get("/Encoding", ""))
        if "KS" in enc or "Korea" in enc or "/Type0" == str(f.get("/Subtype")):
            names.add(name.lstrip("/"))
    return names


def page_text(page) -> str:
    cjk = cjk_font_names(page)
    data = page.get_contents().get_data()
    lines, cur, font = [], [], None
    for m in TOKEN.finditer(data):
        if m.group("font"):
            font = m.group("font").decode("latin-1")
        elif m.group("lit") or m.group("hex"):
            raw = literal_bytes(m.group("lit")) if m.group("lit") else bytes.fromhex(
                re.sub(rb"\s", b"", m.group("hex")[1:-1]).decode())
            enc = "utf-16-be" if font in cjk and len(raw) % 2 == 0 else "latin-1"
            cur.append(raw.decode(enc, "replace"))
        elif m.group("br") and cur:
            lines.append("".join(cur))
            cur = []
    if cur:
        lines.append("".join(cur))
    return "\n".join(l.strip() for l in lines if l.strip())


def extract(path: str) -> str:
    reader = pypdf.PdfReader(path)
    return "\n\n".join(f"--- page {i + 1} ---\n{page_text(p)}" for i, p in enumerate(reader.pages))


if __name__ == "__main__":
    text = extract(sys.argv[1])
    if len(sys.argv) > 2:
        open(sys.argv[2], "w", encoding="utf-8").write(text)
    else:
        print(text)

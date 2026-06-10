"""
md_to_pdf · Markdown 转中文 PDF

自动安装中文字体，解决中文编码/乱码问题，生成带样式的专业 PDF。
"""
import os
import subprocess
import urllib.request


TOOLS = [
    {
        "name": "md_to_pdf",
        "description": "将 Markdown 内容或文件转换为 PDF（自动处理中文编码与字体，解决中文乱码）",
        "parameters": {
            "type": "object",
            "properties": {
                "md_content": {
                    "type": "string",
                    "description": "Markdown 文本内容（与 md_path 二选一）",
                },
                "md_path": {
                    "type": "string",
                    "description": "Markdown 文件路径（与 md_content 二选一），须英文/ASCII 路径",
                },
                "output_path": {
                    "type": "string",
                    "description": "输出 PDF 路径，默认 /home/daytona/report.pdf",
                    "default": "/home/daytona/report.pdf",
                },
                "title": {
                    "type": "string",
                    "description": "文档标题（可选，显示在顶部标题区）",
                },
                "font_size": {
                    "type": "integer",
                    "description": "正文字号（pt），默认 12",
                    "default": 12,
                },
            },
        },
    },
]


def _ensure_chinese_font() -> str:
    """确保中文字体可用，返回字体名称"""
    ret = subprocess.run(
        "fc-list ':lang=zh' 2>/dev/null | head -1",
        shell=True, capture_output=True, text=True
    )
    if ret.stdout.strip():
        name = ret.stdout.split(":")[1].strip().split(",")[0].strip()
        return name

    ret = subprocess.run(
        "fc-list 'Noto Sans SC' 2>/dev/null | head -1",
        shell=True, capture_output=True, text=True
    )
    if ret.stdout.strip():
        return "Noto Sans SC"

    font_dir = os.path.expanduser("~/.fonts")
    os.makedirs(font_dir, exist_ok=True)
    font_path = os.path.join(font_dir, "NotoSansSC.ttf")
    if not os.path.exists(font_path):
        url = ("https://github.com/google/fonts/raw/main/ofl/notosanssc/"
               "NotoSansSC%5Bwght%5D.ttf")
        try:
            urllib.request.urlretrieve(url, font_path)
        except Exception:
            pass
    subprocess.run("fc-cache -f 2>/dev/null", shell=True)
    return "Noto Sans SC"


def md_to_pdf(
    md_content: str = None,
    md_path: str = None,
    output_path: str = "/home/daytona/report.pdf",
    title: str = None,
    font_size: int = 12,
) -> str:
    """
    将 Markdown 内容或文件转换为 PDF（支持中文）。

    自动安装中文字体解决乱码问题，生成带样式的专业 PDF。
    """
    import markdown
    from weasyprint import HTML

    if md_content and md_path:
        raise ValueError("md_content 和 md_path 只能选一个")
    if md_content is None and md_path is None:
        raise ValueError("必须提供 md_content 或 md_path")

    if md_path:
        with open(md_path, "r", encoding="utf-8") as f:
            md_text = f.read()
    else:
        md_text = md_content

    cn_font = _ensure_chinese_font()
    body_html = markdown.markdown(md_text, extensions=["tables", "fenced_code", "codehilite"])

    title_html = ""
    if title:
        title_html = f'<div class="doc-title">{title}</div>'

    fs = font_size
    html_text = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<style>
@page {{
    margin: 2.2cm 2cm 2cm 2cm;
    @bottom-center {{
        content: counter(page);
        font-size: 9pt;
        color: #999;
    }}
}}
body {{
    font-family: '{cn_font}', 'DejaVu Sans', sans-serif;
    font-size: {fs}pt;
    line-height: 1.7;
    color: #222;
}}
.doc-title {{
    font-size: {fs + 6}pt;
    font-weight: bold;
    text-align: center;
    color: #1a1a2e;
    margin-bottom: 20px;
    padding-bottom: 12px;
    border-bottom: 2px solid #e94560;
}}
h1 {{ font-size: {fs + 6}pt; text-align: center; color: #1a1a2e;
     border-bottom: 2px solid #e94560; padding-bottom: 8px; }}
h2 {{ font-size: {fs + 3}pt; color: #16213e;
     border-left: 4px solid #0f3460; padding-left: 10px; margin-top: 28px; }}
h3 {{ font-size: {fs + 1}pt; color: #0f3460; margin-top: 20px; }}
table {{ width: 100%; border-collapse: collapse; margin: 12px 0;
         font-size: {fs - 1}pt; }}
th {{ background-color: #0f3460; color: white; padding: 7px 10px;
      text-align: center; font-weight: bold; }}
td {{ border: 1px solid #ccc; padding: 5px 10px; text-align: center; }}
tr:nth-child(even) {{ background-color: #f5f6fa; }}
blockquote {{ border-left: 4px solid #e94560; padding: 8px 14px;
              background: #fff5f5; margin: 12px 0; font-size: {fs - 1}pt; }}
code {{ font-family: 'Courier New', 'DejaVu Sans Mono', monospace;
        background: #f0f0f0; padding: 1px 4px; border-radius: 3px;
        font-size: {fs - 1}pt; }}
pre {{ background: #282c34; color: #abb2bf; padding: 12px;
       border-radius: 5px; overflow-x: auto; }}
pre code {{ background: transparent; color: inherit; padding: 0; }}
ul, ol {{ margin: 6px 0; padding-left: 24px; }}
li {{ margin: 3px 0; }}
strong {{ color: #e94560; }}
hr {{ border: none; border-top: 1px solid #ddd; margin: 22px 0; }}
</style>
</head>
<body>
{title_html}
{body_html}
</body>
</html>"""

    output_dir = os.path.dirname(output_path)
    if output_dir:
        os.makedirs(output_dir, exist_ok=True)

    HTML(string=html_text).write_pdf(output_path)

    if not os.path.exists(output_path):
        raise RuntimeError(f"PDF 生成失败：{output_path}")

    return output_path

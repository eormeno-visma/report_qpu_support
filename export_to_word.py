"""
Script para convertir README_QUERIES.md a un documento Word (.docx)
manteniendo el diseño: encabezados, tablas, negritas, emojis, bloques de cita, etc.

Uso:
    python export_to_word.py
    python export_to_word.py --input otro_archivo.md --output mi_documento.docx
"""

import re
import argparse
from pathlib import Path

from docx import Document
from docx.shared import Pt, Inches, Cm, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
from docx.enum.style import WD_STYLE_TYPE
from docx.oxml.ns import qn, nsdecls
from docx.oxml import parse_xml


# ─── Configuración de colores ────────────────────────────────────────────────
COLOR_PRIMARY = RGBColor(0x1F, 0x49, 0x7D)     # Azul oscuro (encabezados)
COLOR_SECONDARY = RGBColor(0x2E, 0x75, 0xB6)   # Azul medio (sub-encabezados)
COLOR_ACCENT = RGBColor(0x00, 0x70, 0xC0)       # Azul acento
COLOR_BLOCKQUOTE_BG = "E8F0FE"                   # Fondo azul claro blockquotes
COLOR_BLOCKQUOTE_BORDER = "2E75B6"               # Borde blockquote
COLOR_TABLE_HEADER = "1F497D"                     # Fondo encabezado tabla
COLOR_TABLE_ALT_ROW = "F2F7FB"                   # Fondo fila alterna tabla
COLOR_CODE_BG = "F5F5F5"                          # Fondo código
COLOR_TIP_BG = "E8F5E9"                           # Fondo tips (💡)
COLOR_WARNING_BG = "FFF8E1"                       # Fondo warnings (⚠️)


def setup_styles(doc: Document):
    """Configura estilos personalizados en el documento."""
    styles = doc.styles

    # ── Estilo Normal ──
    style_normal = styles['Normal']
    style_normal.font.name = 'Calibri'
    style_normal.font.size = Pt(11)
    style_normal.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
    style_normal.paragraph_format.space_after = Pt(6)
    style_normal.paragraph_format.line_spacing = 1.15

    # ── Encabezados ──
    for i in range(1, 5):
        h = styles[f'Heading {i}']
        h.font.name = 'Calibri'
        h.font.color.rgb = COLOR_PRIMARY if i <= 2 else COLOR_SECONDARY
        h.font.bold = True
        if i == 1:
            h.font.size = Pt(22)
            h.paragraph_format.space_before = Pt(24)
            h.paragraph_format.space_after = Pt(12)
        elif i == 2:
            h.font.size = Pt(16)
            h.paragraph_format.space_before = Pt(18)
            h.paragraph_format.space_after = Pt(8)
        elif i == 3:
            h.font.size = Pt(13)
            h.paragraph_format.space_before = Pt(12)
            h.paragraph_format.space_after = Pt(6)
        else:
            h.font.size = Pt(11)
            h.paragraph_format.space_before = Pt(8)
            h.paragraph_format.space_after = Pt(4)

    # ── Estilo Blockquote ──
    if 'Blockquote' not in [s.name for s in styles]:
        bq = styles.add_style('Blockquote', WD_STYLE_TYPE.PARAGRAPH)
        bq.font.name = 'Calibri'
        bq.font.size = Pt(10.5)
        bq.font.italic = True
        bq.font.color.rgb = RGBColor(0x55, 0x55, 0x55)
        bq.paragraph_format.left_indent = Cm(1)
        bq.paragraph_format.space_after = Pt(6)
        bq.paragraph_format.line_spacing = 1.15

    # ── Estilo Code ──
    if 'CodeBlock' not in [s.name for s in styles]:
        cb = styles.add_style('CodeBlock', WD_STYLE_TYPE.PARAGRAPH)
        cb.font.name = 'Consolas'
        cb.font.size = Pt(9)
        cb.font.color.rgb = RGBColor(0x33, 0x33, 0x33)
        cb.paragraph_format.left_indent = Cm(0.5)
        cb.paragraph_format.space_after = Pt(2)
        cb.paragraph_format.line_spacing = 1.0

    # ── Estilo List Bullet ──
    if 'List Bullet' in [s.name for s in styles]:
        lb = styles['List Bullet']
        lb.font.name = 'Calibri'
        lb.font.size = Pt(11)


def set_cell_shading(cell, color_hex: str):
    """Aplica color de fondo a una celda de tabla."""
    shading = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{color_hex}" w:val="clear"/>')
    cell._tc.get_or_add_tcPr().append(shading)


def set_paragraph_shading(paragraph, color_hex: str):
    """Aplica color de fondo a un párrafo."""
    shading = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{color_hex}" w:val="clear"/>')
    paragraph._p.get_or_add_pPr().append(shading)


def add_horizontal_line(doc: Document):
    """Agrega una línea horizontal como separador."""
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(6)
    p.paragraph_format.space_after = Pt(6)
    # Línea mediante borde inferior del párrafo
    pPr = p._p.get_or_add_pPr()
    pBdr = parse_xml(
        f'<w:pBdr {nsdecls("w")}>'
        f'  <w:bottom w:val="single" w:sz="6" w:space="1" w:color="CCCCCC"/>'
        f'</w:pBdr>'
    )
    pPr.append(pBdr)


def add_rich_text(paragraph, text: str):
    """
    Procesa texto con formato inline de Markdown y lo agrega al párrafo.
    Soporta: **negrita**, *cursiva*, `código`, [links](url)
    """
    # Patrón para detectar formatos inline
    # Orden: código inline, negrita, cursiva, links
    pattern = re.compile(
        r'(`[^`]+`)'                    # código inline
        r'|(\*\*[^*]+\*\*)'            # negrita
        r'|(\*[^*]+\*)'                # cursiva
        r'|(\[[^\]]+\]\([^)]+\))'      # links
    )

    pos = 0
    for match in pattern.finditer(text):
        # Texto plano antes del match
        if match.start() > pos:
            run = paragraph.add_run(text[pos:match.start()])
            run.font.name = 'Calibri'
            run.font.size = Pt(11)

        code, bold, italic, link = match.groups()

        if code:
            content = code[1:-1]  # quitar backticks
            run = paragraph.add_run(content)
            run.font.name = 'Consolas'
            run.font.size = Pt(9.5)
            run.font.color.rgb = RGBColor(0xC7, 0x25, 0x4E)
            # Fondo gris para código inline es complejo en python-docx, usamos color
        elif bold:
            content = bold[2:-2]  # quitar **
            # Recursivamente procesar contenido interno (puede tener código)
            run = paragraph.add_run(content)
            run.bold = True
            run.font.name = 'Calibri'
            run.font.size = Pt(11)
        elif italic:
            content = italic[1:-1]  # quitar *
            run = paragraph.add_run(content)
            run.italic = True
            run.font.name = 'Calibri'
            run.font.size = Pt(11)
        elif link:
            link_match = re.match(r'\[([^\]]+)\]\(([^)]+)\)', link)
            if link_match:
                link_text = link_match.group(1)
                run = paragraph.add_run(link_text)
                run.font.name = 'Calibri'
                run.font.size = Pt(11)
                run.font.color.rgb = COLOR_ACCENT
                run.underline = True

        pos = match.end()

    # Texto restante
    if pos < len(text):
        run = paragraph.add_run(text[pos:])
        run.font.name = 'Calibri'
        run.font.size = Pt(11)


def parse_markdown_table(lines: list[str]) -> tuple[list[str], list[list[str]]]:
    """Parsea una tabla Markdown y devuelve headers y filas."""
    headers = []
    rows = []

    for i, line in enumerate(lines):
        cells = [c.strip() for c in line.strip('|').split('|')]
        if i == 0:
            headers = cells
        elif i == 1:
            # Línea separadora (---|---|---)
            continue
        else:
            rows.append(cells)

    return headers, rows


def add_styled_table(doc: Document, headers: list[str], rows: list[list[str]]):
    """Agrega una tabla estilizada al documento."""
    num_cols = len(headers)
    table = doc.add_table(rows=1 + len(rows), cols=num_cols)
    table.alignment = WD_TABLE_ALIGNMENT.CENTER
    table.style = 'Table Grid'

    # Ancho total
    table.autofit = True

    # ── Encabezados ──
    for j, header in enumerate(headers):
        cell = table.rows[0].cells[j]
        cell.text = ''
        p = cell.paragraphs[0]
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        run = p.add_run(header)
        run.bold = True
        run.font.name = 'Calibri'
        run.font.size = Pt(10)
        run.font.color.rgb = RGBColor(0xFF, 0xFF, 0xFF)
        set_cell_shading(cell, COLOR_TABLE_HEADER)

    # ── Filas de datos ──
    for i, row_data in enumerate(rows):
        for j in range(min(len(row_data), num_cols)):
            cell = table.rows[i + 1].cells[j]
            cell.text = ''
            p = cell.paragraphs[0]
            add_rich_text(p, row_data[j])
            p.paragraph_format.space_after = Pt(2)
            p.paragraph_format.space_before = Pt(2)

            # Fondo alterno
            if i % 2 == 1:
                set_cell_shading(cell, COLOR_TABLE_ALT_ROW)

    doc.add_paragraph()  # Espacio después de tabla


def process_blockquote(doc: Document, lines: list[str]):
    """Procesa un bloque de cita (> texto)."""
    content = ' '.join(line.lstrip('> ').strip() for line in lines)

    p = doc.add_paragraph(style='Blockquote')

    # Detectar tipo de blockquote por emoji
    if '💡' in content:
        set_paragraph_shading(p, COLOR_TIP_BG)
    elif '⚠️' in content or '⚠' in content:
        set_paragraph_shading(p, COLOR_WARNING_BG)
    else:
        set_paragraph_shading(p, COLOR_BLOCKQUOTE_BG)

    # Agregar borde izquierdo
    pPr = p._p.get_or_add_pPr()
    pBdr = parse_xml(
        f'<w:pBdr {nsdecls("w")}>'
        f'  <w:left w:val="single" w:sz="18" w:space="8" w:color="{COLOR_BLOCKQUOTE_BORDER}"/>'
        f'</w:pBdr>'
    )
    pPr.append(pBdr)

    add_rich_text(p, content)


def convert_md_to_docx(input_path: str, output_path: str):
    """Convierte un archivo Markdown a Word (.docx) con diseño profesional."""

    doc = Document()

    # ── Configurar márgenes ──
    for section in doc.sections:
        section.top_margin = Cm(2)
        section.bottom_margin = Cm(2)
        section.left_margin = Cm(2.5)
        section.right_margin = Cm(2.5)

    setup_styles(doc)

    # ── Leer archivo Markdown ──
    with open(input_path, 'r', encoding='utf-8') as f:
        lines = f.readlines()

    i = 0
    total_lines = len(lines)

    while i < total_lines:
        line = lines[i].rstrip('\n')
        stripped = line.strip()

        # ── Línea vacía ──
        if not stripped:
            i += 1
            continue

        # ── Separador horizontal (---) ──
        if re.match(r'^-{3,}$', stripped):
            add_horizontal_line(doc)
            i += 1
            continue

        # ── Bloque de código (```) ──
        if stripped.startswith('```'):
            i += 1
            code_lines = []
            while i < total_lines and not lines[i].strip().startswith('```'):
                code_lines.append(lines[i].rstrip('\n'))
                i += 1
            i += 1  # saltar el cierre ```

            # Agregar bloque de código
            for cl in code_lines:
                p = doc.add_paragraph(style='CodeBlock')
                set_paragraph_shading(p, COLOR_CODE_BG)
                run = p.add_run(cl)
                run.font.name = 'Consolas'
                run.font.size = Pt(9)
            doc.add_paragraph()  # espacio después
            continue

        # ── Encabezados (#, ##, ###, ####) ──
        heading_match = re.match(r'^(#{1,4})\s+(.+)$', stripped)
        if heading_match:
            level = len(heading_match.group(1))
            text = heading_match.group(2)
            p = doc.add_heading(text, level=level)
            i += 1
            continue

        # ── Tabla Markdown ──
        if '|' in stripped and stripped.startswith('|'):
            table_lines = []
            while i < total_lines and '|' in lines[i].strip() and lines[i].strip().startswith('|'):
                table_lines.append(lines[i].strip())
                i += 1

            if len(table_lines) >= 2:  # al menos header + separador
                headers, rows = parse_markdown_table(table_lines)
                if headers and rows:
                    add_styled_table(doc, headers, rows)
            continue

        # ── Blockquote (> texto) ──
        if stripped.startswith('>'):
            bq_lines = []
            while i < total_lines and lines[i].strip().startswith('>'):
                bq_lines.append(lines[i].strip())
                i += 1
            process_blockquote(doc, bq_lines)
            continue

        # ── Lista con viñeta (- item o * item) ──
        list_match = re.match(r'^(\s*)([-*])\s+(.+)$', stripped)
        if list_match:
            text = list_match.group(3)
            indent_level = len(list_match.group(1)) // 2

            p = doc.add_paragraph(style='List Bullet')
            if indent_level > 0:
                p.paragraph_format.left_indent = Cm(1.27 * (indent_level + 1))
            add_rich_text(p, text)
            i += 1
            continue

        # ── Lista numerada (1. item) ──
        num_list_match = re.match(r'^(\d+)\.\s+(.+)$', stripped)
        if num_list_match:
            text = num_list_match.group(2)
            p = doc.add_paragraph(style='List Number')
            add_rich_text(p, text)
            i += 1
            continue

        # ── Párrafo normal ──
        p = doc.add_paragraph()
        add_rich_text(p, stripped)
        i += 1

    # ── Agregar pie de página ──
    section = doc.sections[-1]
    footer = section.footer
    footer.is_linked_to_previous = False
    fp = footer.paragraphs[0]
    fp.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = fp.add_run("Documento generado automáticamente desde README_QUERIES.md")
    run.font.name = 'Calibri'
    run.font.size = Pt(8)
    run.font.color.rgb = RGBColor(0x99, 0x99, 0x99)

    # ── Guardar ──
    doc.save(output_path)
    print(f"✅ Documento generado exitosamente: {output_path}")


def main():
    parser = argparse.ArgumentParser(description='Convertir Markdown a Word (.docx)')
    parser.add_argument('--input', '-i', default='README_QUERIES.md',
                        help='Archivo Markdown de entrada (default: README_QUERIES.md)')
    parser.add_argument('--output', '-o', default='output/README_QUERIES.docx',
                        help='Archivo Word de salida (default: output/README_QUERIES.docx)')
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        print(f"❌ Error: No se encontró el archivo '{input_path}'")
        return

    # Crear directorio de salida si no existe
    output_path.parent.mkdir(parents=True, exist_ok=True)

    convert_md_to_docx(str(input_path), str(output_path))


if __name__ == '__main__':
    main()


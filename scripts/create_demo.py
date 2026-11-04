"""Create synthetic demo PDFs locally (never uses real customer artwork)."""
from pathlib import Path
from reportlab.pdfgen import canvas


def build(path: Path, modified: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = canvas.Canvas(str(path), pagesize=(420, 300), pageCompression=0)
    pdf.setFont("Helvetica", 16)
    pdf.drawString(35, 254, "CLIENT APPROVFD" if modified else "CLIENT APPROVED")
    pdf.setLineWidth(0.7 if modified else 0.4)
    pdf.line(35, 206, 382, 206)
    pdf.setFillColorRGB(0.15, 0.52 if modified else 0.37, 0.78)
    pdf.rect(35, 65, 140, 97, fill=1, stroke=0)
    pdf.setStrokeColorRGB(.1, .15, .15)
    pdf.setLineWidth(1.5)
    pdf.bezier(211, 145, 240, 200, 280.9 if modified else 280, 115, 349, 152)
    if modified:
        pdf.circle(363, 96, 2.5, fill=1, stroke=0)
    pdf.showPage()
    pdf.save()


if __name__ == "__main__":
    build(Path("demo/approved.pdf"), False)
    build(Path("demo/production.pdf"), True)
    print("Created demo/approved.pdf and demo/production.pdf")

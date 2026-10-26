"""Generate a comprehensive, professionally styled PDF guide for the AI E-Challan System."""

import os
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, HRFlowable
)
from reportlab.pdfgen import canvas


class NumberedCanvas(canvas.Canvas):
    """Two-pass canvas to dynamically compute and print total page numbers."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_header_footer(num_pages)
            canvas.Canvas.showPage(self)
        canvas.Canvas.save(self)

    def draw_header_footer(self, page_count):
        self.saveState()
        self.setFont("Helvetica-Bold", 8)
        self.setFillColor(colors.HexColor("#475569"))

        # Header (pages after page 1)
        if self._pageNumber > 1:
            self.drawString(54, 755, "AI-Driven RTO E-Challan System — Project Execution & Deployment Guide")
            self.setStrokeColor(colors.HexColor("#cbd5e1"))
            self.setLineWidth(0.6)
            self.line(54, 747, 558, 747)

        # Footer (all pages)
        self.setStrokeColor(colors.HexColor("#cbd5e1"))
        self.setLineWidth(0.6)
        self.line(54, 42, 558, 42)
        self.setFont("Helvetica", 8)
        self.setFillColor(colors.HexColor("#64748b"))
        self.drawString(54, 30, "AI RTO E-Challan System | Confidential & Academic Reference")
        page_text = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(558, 30, page_text)
        self.restoreState()


def create_guide_pdf(filename="PROJECT_RUN_GUIDE.pdf"):
    doc = SimpleDocTemplate(
        filename,
        pagesize=letter,
        leftMargin=50,
        rightMargin=50,
        topMargin=48,
        bottomMargin=48,
    )

    styles = getSampleStyleSheet()

    c_primary = colors.HexColor("#0f172a")
    c_blue = colors.HexColor("#1d4ed8")
    c_dark = colors.HexColor("#334155")
    c_bg_code = colors.HexColor("#f8fafc")
    c_callout_bg = colors.HexColor("#eff6ff")
    c_callout_border = colors.HexColor("#3b82f6")

    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=20,
        leading=24,
        textColor=c_primary,
        spaceAfter=3,
    )

    subtitle_style = ParagraphStyle(
        'DocSubTitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=10,
        leading=13,
        textColor=colors.HexColor("#475569"),
        spaceAfter=10,
    )

    h1_style = ParagraphStyle(
        'SectionH1',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=12.5,
        leading=16,
        textColor=c_blue,
        spaceBefore=10,
        spaceAfter=4,
        keepWithNext=True,
    )

    h2_style = ParagraphStyle(
        'SectionH2',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=13,
        textColor=c_primary,
        spaceBefore=6,
        spaceAfter=3,
        keepWithNext=True,
    )

    body_style = ParagraphStyle(
        'BodyDark',
        parent=styles['BodyText'],
        fontName='Helvetica',
        fontSize=8.8,
        leading=12.2,
        textColor=c_dark,
        spaceAfter=4,
    )

    bullet_style = ParagraphStyle(
        'BulletText',
        parent=body_style,
        leftIndent=12,
        firstLineIndent=-8,
        spaceAfter=2.5,
    )

    code_style = ParagraphStyle(
        'CodeText',
        parent=styles['Normal'],
        fontName='Courier',
        fontSize=8.2,
        leading=10.5,
        textColor=colors.HexColor("#0f172a"),
    )

    table_cell = ParagraphStyle(
        'TableCell',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=10.5,
        textColor=c_dark,
    )

    table_header = ParagraphStyle(
        'TableHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10.5,
        textColor=colors.white,
    )

    def code_box(text):
        p = Paragraph(f"<b>$</b> {text.replace(chr(10), '<br/><b>$</b> ')}", code_style)
        t = Table([[p]], colWidths=[512])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), c_bg_code),
            ('BOX', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
            ('LEFTPADDING', (0,0), (-1,-1), 8),
            ('RIGHTPADDING', (0,0), (-1,-1), 8),
            ('TOPPADDING', (0,0), (-1,-1), 4),
            ('BOTTOMPADDING', (0,0), (-1,-1), 4),
        ]))
        return t

    def callout_box(text, title="IMPORTANT NOTICE"):
        p_title = Paragraph(f"<b>{title}</b>", ParagraphStyle('CT', parent=body_style, fontName='Helvetica-Bold', textColor=c_blue, fontSize=8.5, leading=11))
        p_text = Paragraph(text, ParagraphStyle('CText', parent=body_style, fontSize=8.2, leading=11.2, spaceAfter=0))
        t = Table([[p_title], [p_text]], colWidths=[512])
        t.setStyle(TableStyle([
            ('BACKGROUND', (0,0), (-1,-1), c_callout_bg),
            ('BOX', (0,0), (-1,-1), 0.8, c_callout_border),
            ('LEFTPADDING', (0,0), (-1,-1), 10),
            ('RIGHTPADDING', (0,0), (-1,-1), 10),
            ('TOPPADDING', (0,0), (-1,-1), 5),
            ('BOTTOMPADDING', (0,0), (-1,-1), 5),
        ]))
        return t

    story = []

    # =========================================================================
    # PAGE 1: System Overview, Credentials, and Cloud Deployment (Render.com)
    # =========================================================================
    story.append(Paragraph("AI-Driven RTO E-Challan System", title_style))
    story.append(Paragraph("Complete Project Execution Guide | Cloud (Render) & Localhost Environments", subtitle_style))
    story.append(HRFlowable(width="100%", thickness=1.5, color=c_blue, spaceBefore=0, spaceAfter=8))

    story.append(Paragraph("1. System Overview & Default Login Credentials", h1_style))
    story.append(Paragraph(
        "The system is an automated AI traffic enforcement platform. It ingests video feeds from RTSP cameras, "
        "mobile webcams, recorded clips, or a built-in synthetic generator. Violations (Speeding, No Helmet, Triple Riding, "
        "Red Light) are detected via Groq Vision AI, license plates read via ANPR, vehicle owners retrieved from MongoDB Atlas, "
        "SMS notifications delivered via Fast2SMS, and fines collected via Razorpay test gateway.",
        body_style
    ))

    cred_data = [
        [Paragraph("Role", table_header), Paragraph("Username", table_header), Paragraph("Password", table_header), Paragraph("Accessible Features", table_header)],
        [Paragraph("Administrator", table_cell), Paragraph("<b>admin</b>", table_cell), Paragraph("admin123", table_cell), Paragraph("Full control: Camera management, AI settings, Rules, Users, Challans, Analytics", table_cell)],
        [Paragraph("Traffic Officer", table_cell), Paragraph("<b>officer1</b>", table_cell), Paragraph("officer123", table_cell), Paragraph("Operational control: Live monitoring, Manual review, Challan approval & status", table_cell)],
    ]
    t_cred = Table(cred_data, colWidths=[85, 75, 75, 277])
    t_cred.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), c_blue),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('TOPPADDING', (0,0), (-1,-1), 3.5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3.5),
        ('LEFTPADDING', (0,0), (-1,-1), 6),
        ('RIGHTPADDING', (0,0), (-1,-1), 6),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor("#f8fafc")]),
    ]))
    story.append(t_cred)
    story.append(Spacer(1, 6))

    story.append(Paragraph("2. Running the Cloud Deployment (Render.com)", h1_style))
    story.append(Paragraph(
        "Live Production URL: <b>https://ai-echallan-system-1.onrender.com</b><br/>"
        "The cloud instance serves the unified React frontend and FastAPI backend directly from Docker on Render.",
        body_style
    ))

    story.append(Paragraph("Option A: Zero-Hardware Testing with Built-in Demo Camera (CAM-02)", h2_style))
    story.append(Paragraph("• <b>Step 1:</b> Log in to <b>https://ai-echallan-system-1.onrender.com</b> with <code>admin</code> / <code>admin123</code>.", bullet_style))
    story.append(Paragraph("• <b>Step 2:</b> Navigate to <b>Live Monitoring</b> in the top navigation bar.", bullet_style))
    story.append(Paragraph("• <b>Step 3:</b> Under <b>CAM-02 (Marine Drive North)</b>, use the <b>'Demo Active' / 'Demo Paused'</b> toggle button to control traffic generation.", bullet_style))
    story.append(Paragraph("• <b>Step 4:</b> Simulated speeding cars and riders without helmets will trigger real-time AI detections and automatic challans.", bullet_style))

    story.append(Paragraph("Option B: Connecting a Real Mobile Phone Camera to the Cloud (Render)", h2_style))
    story.append(Paragraph(
        "Render is hosted in a cloud data center and cannot reach private local Wi-Fi IPs (like <code>10.173.33.193</code>) directly. "
        "Use a free secure tunnel (Pinggy) from your laptop to expose the feed publicly:",
        body_style
    ))
    story.append(Paragraph("1. Install <b>IP Webcam</b> from Google Play Store on your Android phone.", bullet_style))
    story.append(Paragraph("2. Connect your phone and laptop to the <b>same Wi-Fi or mobile hotspot</b>.", bullet_style))
    story.append(Paragraph("3. Open IP Webcam, tap <b>Start server</b>, and note the IP at the bottom (e.g. <code>http://10.173.33.193:8080</code>).", bullet_style))
    story.append(Paragraph("4. Open <b>PowerShell</b> on your laptop and run (zero install required):", bullet_style))
    story.append(Spacer(1, 2))
    story.append(code_box("ssh -p 443 -R0:10.173.33.193:8080 qr@a.pinggy.io"))
    story.append(Spacer(1, 2))
    story.append(Paragraph("5. Pinggy displays an HTTPS URL, for example: <code>https://random-subdomain.a.free.pinggy.link</code>.", bullet_style))
    story.append(Paragraph("6. In the Render website, go to <b>Cameras</b> &rarr; Click <b>Edit</b> on <b>CAM-01</b>.", bullet_style))
    story.append(Paragraph("7. Set <b>Stream URL / RTSP URL</b> to: <code>https://random-subdomain.a.free.pinggy.link/video</code>.", bullet_style))
    story.append(Paragraph("8. Click <b>Test Connection</b> &rarr; It will report <i>'Connected and received a frame'</i> &rarr; Click <b>Save</b>.", bullet_style))
    story.append(Paragraph("9. Open <b>Live Monitoring</b>: Your physical mobile camera feed is now live on the Render cloud platform!", bullet_style))

    story.append(Paragraph("Option C: Direct Image & Video Upload", h2_style))
    story.append(Paragraph("• Click <b>Upload Video / Image</b> in the navbar &rarr; Drag and drop recorded traffic footage for instant AI analysis.", bullet_style))

    story.append(PageBreak())

    # =========================================================================
    # PAGE 2: Local Execution and End-to-End Workflow Table
    # =========================================================================
    story.append(Paragraph("3. Running the Project Locally (Laptop / PC)", h1_style))
    story.append(Paragraph(
        "For offline presentations or local testing with direct phone camera feeds (no tunneling needed):",
        body_style
    ))

    story.append(Paragraph("Prerequisites", h2_style))
    story.append(Paragraph("• <b>Python 3.10+</b> (with 'Add Python to PATH' enabled during installation).", bullet_style))
    story.append(Paragraph("• <b>Node.js 18+</b> and npm installed.", bullet_style))
    story.append(Paragraph("• <b>Git</b> installed.", bullet_style))

    story.append(Paragraph("One-Click Automated Launch (Recommended)", h2_style))
    story.append(Paragraph(
        "Double-click <b>START.bat</b> in the project root folder. It self-heals by validating or re-creating the virtual environment, "
        "installing requirements, building npm packages, and starting both servers automatically:",
        body_style
    ))
    story.append(code_box("START.bat"))
    story.append(Paragraph("• <b>Frontend:</b> http://localhost:5173 | <b>Backend API:</b> http://localhost:8000 | <b>Docs:</b> http://localhost:8000/docs", body_style))

    story.append(Paragraph("Direct Mobile Camera on Localhost (No Tunnel Required)", h2_style))
    story.append(Paragraph(
        "Because laptop and phone share the same Wi-Fi, you can use the raw local IP directly:",
        body_style
    ))
    story.append(Paragraph("1. Open <b>http://localhost:5173</b> and log in as <code>admin</code>.", bullet_style))
    story.append(Paragraph("2. Go to <b>Cameras</b> &rarr; Click <b>Edit</b> on <b>CAM-01</b>.", bullet_style))
    story.append(Paragraph("3. Enter direct phone IP Webcam URL: <code>http://10.173.33.193:8080/video</code> &rarr; Click <b>Test Connection</b> &rarr; <b>Save</b>.", bullet_style))

    story.append(Spacer(1, 4))
    story.append(Paragraph("4. Complete End-to-End E-Challan Workflow", h1_style))
    story.append(Paragraph(
        "The following sequential steps demonstrate the entire lifecycle of an automated traffic violation:",
        body_style
    ))

    flow_data = [
        [Paragraph("Step", table_header), Paragraph("Stage", table_header), Paragraph("Process Description & Expected Output", table_header)],
        [Paragraph("1", table_cell), Paragraph("Violation Ingestion", table_cell), Paragraph("Live camera or CAM-02 detects a speed breach (>60 km/h), missing helmet, triple riding, or red light violation.", table_cell)],
        [Paragraph("2", table_cell), Paragraph("Vision AI Analysis", table_cell), Paragraph("Groq Vision AI (Qwen 2.5-VL) validates the violation bbox and vehicle type from high-resolution frame crop.", table_cell)],
        [Paragraph("3", table_cell), Paragraph("ANPR Plate OCR", table_cell), Paragraph("Plate Recognizer / EasyOCR extracts license number (e.g., <b>MH29CE7640</b>) with confidence score.", table_cell)],
        [Paragraph("4", table_cell), Paragraph("RTO Database Match", table_cell), Paragraph("MongoDB Atlas matches registration to registered owner: <b>Nivedita Ingole</b> (Phone: <b>9370077413</b>).", table_cell)],
        [Paragraph("5", table_cell), Paragraph("SMS Dispatch", table_cell), Paragraph("Fast2SMS sends automated SMS with challan number, fine amount, due date, and online payment URL.", table_cell)],
        [Paragraph("6", table_cell), Paragraph("Officer Verification", table_cell), Paragraph("Traffic officer inspects evidence snapshot, radar speed trace, and timestamps on <b>E-Challans</b> page.", table_cell)],
        [Paragraph("7", table_cell), Paragraph("Citizen Online Payment", table_cell), Paragraph("Click <b>Pay Now</b> &rarr; Razorpay test modal processes payment &rarr; Status changes to <b>PAID</b> with digital receipt.", table_cell)],
        [Paragraph("8", table_cell), Paragraph("Public Portal Lookup", table_cell), Paragraph("Citizen opens <code>/public</code> &rarr; Enters vehicle <b>MH29CE7640</b> &rarr; Views and pays notice without logging in.", table_cell)],
    ]
    t_flow = Table(flow_data, colWidths=[32, 115, 365])
    t_flow.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), c_blue),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3),
        ('LEFTPADDING', (0,0), (-1,-1), 5),
        ('RIGHTPADDING', (0,0), (-1,-1), 5),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor("#f8fafc")]),
    ]))
    story.append(t_flow)

    story.append(PageBreak())

    # =========================================================================
    # PAGE 3: API Configurations, Fast2SMS Clarification, and FAQ / Troubleshooting
    # =========================================================================
    story.append(Paragraph("5. API Integrations & Cloud Infrastructure", h1_style))
    story.append(Paragraph("All third-party services are active in <code>backend/.env</code> and MongoDB Atlas:", body_style))

    api_data = [
        [Paragraph("Service", table_header), Paragraph("Provider", table_header), Paragraph("Current State", table_header), Paragraph("Technical Purpose & Specifications", table_header)],
        [Paragraph("Vision AI", table_cell), Paragraph("Groq Cloud", table_cell), Paragraph("ACTIVE", table_cell), Paragraph("qwen/qwen3.8-27b model for high-speed multi-violation detection", table_cell)],
        [Paragraph("ANPR / OCR", table_cell), Paragraph("Plate Recognizer", table_cell), Paragraph("ACTIVE", table_cell), Paragraph("Cloud API for Indian high-security registration plate character reading", table_cell)],
        [Paragraph("Fallback OCR", table_cell), Paragraph("OCR.Space", table_cell), Paragraph("ACTIVE", table_cell), Paragraph("Secondary OCR engine for adverse lighting or noisy plates", table_cell)],
        [Paragraph("SMS Gateway", table_cell), Paragraph("Fast2SMS", table_cell), Paragraph("READY (Wallet)", table_cell), Paragraph("v2 bulk API for automated SMS notifications (Requires Rs. 100 recharge)", table_cell)],
        [Paragraph("Payment Gateway", table_cell), Paragraph("Razorpay", table_cell), Paragraph("ACTIVE (Test)", table_cell), Paragraph("Standard Indian payment gateway for instant simulated fine collection", table_cell)],
        [Paragraph("Database", table_cell), Paragraph("MongoDB Atlas", table_cell), Paragraph("ACTIVE (Cloud)", table_cell), Paragraph("Cloud cluster holding vehicles, challans, cameras, users, and audit logs", table_cell)],
    ]
    t_api = Table(api_data, colWidths=[75, 90, 75, 272])
    t_api.setStyle(TableStyle([
        ('BACKGROUND', (0,0), (-1,0), c_blue),
        ('GRID', (0,0), (-1,-1), 0.5, colors.HexColor("#cbd5e1")),
        ('TOPPADDING', (0,0), (-1,-1), 3.5),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3.5),
        ('LEFTPADDING', (0,0), (-1,-1), 5),
        ('RIGHTPADDING', (0,0), (-1,-1), 5),
        ('ROWBACKGROUNDS', (0,1), (-1,-1), [colors.white, colors.HexColor("#f8fafc")]),
    ]))
    story.append(t_api)
    story.append(Spacer(1, 5))

    story.append(callout_box(
        "<b>Fast2SMS Activation Note:</b> Newly created Fast2SMS developer accounts require a one-time wallet recharge of "
        "<b>Rs. 100 INR</b> or more at fast2sms.com/dashboard to unlock programmatic API SMS dispatch. "
        "The project backend code is already fully configured and ready — the moment your Fast2SMS wallet has a balance of "
        "Rs. 100+, SMS alerts will dispatch automatically to the violator's phone with <b>zero code changes</b>.",
        "FAST2SMS WALLET ACTIVATION CONFIRMATION"
    ))
    story.append(Spacer(1, 6))

    story.append(Paragraph("6. Frequently Asked Questions & Troubleshooting", h1_style))

    story.append(Paragraph("Q1: Why did Render show 'Could not connect to http://10.173.33.193:8080/video'?", h2_style))
    story.append(Paragraph(
        "<b>Ans:</b> <code>10.173.33.193</code> is a private IP inside your local Wi-Fi router. Render is hosted in a public "
        "cloud data center and has no route into private home Wi-Fi networks. Solution: Use the Pinggy command (<code>ssh -p 443 -R0:... qr@a.pinggy.io</code>) "
        "to forward the feed to a public HTTPS link, or run locally via <code>START.bat</code>.",
        body_style
    ))

    story.append(Paragraph("Q2: Do I need to change the phone IP address every time?", h2_style))
    story.append(Paragraph(
        "<b>Ans:</b> If your phone stays connected to the same Wi-Fi / hotspot, the IP usually remains the same. If you restart "
        "your phone or change Wi-Fi networks, check the IP displayed at the bottom of the IP Webcam app screen (e.g. <code>http://10.173.33.205:8080</code>) "
        "and update the IP in your Pinggy command accordingly.",
        body_style
    ))

    story.append(Paragraph("Q3: Does the Pinggy web URL change every time I run it?", h2_style))
    story.append(Paragraph(
        "<b>Ans:</b> Yes. Free Pinggy URLs are temporary and regenerate each time you re-open PowerShell and start the command. "
        "Whenever you start a new session, copy the new URL into <b>Cameras &rarr; CAM-01 &rarr; Stream URL</b>.",
        body_style
    ))

    story.append(Paragraph("Q4: What if the browser shows '500 Proxy Error' or 'Connection Refused' locally?", h2_style))
    story.append(Paragraph(
        "<b>Ans:</b> This means the backend server is not running on port 8000. Simply double-click <code>START.bat</code>. "
        "It will launch both backend and frontend together with automatic dependency resolution.",
        body_style
    ))

    story.append(Paragraph("Q5: Can I demonstrate the project without any phone camera connected?", h2_style))
    story.append(Paragraph(
        "<b>Ans:</b> Yes! Simply use <b>CAM-02 (Demo Mode)</b> or the <b>Upload Video / Image</b> page. CAM-02 runs natively "
        "both in the cloud and locally, generating real-time traffic and violations with zero hardware requirements.",
        body_style
    ))

    # Build document
    doc.build(story, canvasmaker=NumberedCanvas)
    print(f"PDF successfully generated: {filename}")


if __name__ == "__main__":
    create_guide_pdf("d:/Workspace/Ai-echallan-system-main/PROJECT_RUN_GUIDE.pdf")

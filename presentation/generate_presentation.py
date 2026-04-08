"""
Talos CleanRoom Capstone Presentation Generator

Generates a 13-slide PowerPoint presentation using the StMU 2024 template.
Usage: python presentation/generate_presentation.py
"""

import os
from pathlib import Path
from pptx import Presentation
from pptx.util import Inches, Pt, Emu
from pptx.dml.color import RGBColor
from pptx.enum.text import PP_ALIGN, MSO_ANCHOR
from pptx.enum.shapes import MSO_SHAPE

# --- Paths ---
REPO_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE_PATH = Path(r"C:\Users\Administrator\Downloads\General_StMU Template_2024.pptx")
OUTPUT_PATH = REPO_ROOT / "presentation" / "Talos-CleanRoom-Capstone.pptx"
IMG_DIR = REPO_ROOT / "docs" / "user-guide" / "docs" / "img"
VIDEO_DIR = REPO_ROOT / "docs" / "user-guide" / "docs" / "videos"

# --- Colors ---
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
LIGHT_GRAY = RGBColor(0xD1, 0xD5, 0xDB)
MED_GRAY = RGBColor(0x9C, 0xA3, 0xAF)
DARK_BG = RGBColor(0x1F, 0x2A, 0x37)
DARKER_BG = RGBColor(0x11, 0x18, 0x27)
CYAN = RGBColor(0x22, 0xD3, 0xEE)
GREEN = RGBColor(0x4A, 0xDE, 0x80)
RED = RGBColor(0xF8, 0x71, 0x71)
YELLOW = RGBColor(0xFB, 0xBF, 0x24)
BLUE = RGBColor(0x60, 0xA5, 0xFA)
INDIGO = RGBColor(0x81, 0x8C, 0xF8)
ORANGE = RGBColor(0xFB, 0x92, 0x3C)
TEAL = RGBColor(0x2D, 0xD4, 0xBF)

# Architecture diagram colors
PROXMOX_COLOR = RGBColor(0xE7, 0x6F, 0x00)  # Proxmox orange
K8S_COLOR = RGBColor(0x32, 0x6C, 0xE5)       # K8s blue
INFRA_COLOR = RGBColor(0x6B, 0x72, 0x80)      # Gray
SECURITY_COLOR = RGBColor(0xDC, 0x26, 0x26)   # Red
APP_COLOR = RGBColor(0x05, 0x96, 0x69)        # Green
LXC_COLOR = RGBColor(0x7C, 0x3A, 0xED)        # Purple

# Layout indices
LAYOUT_TITLE = 0
LAYOUT_TITLE_CONTENT = 1
LAYOUT_SECTION = 2
LAYOUT_TWO_CONTENT = 3
LAYOUT_COMPARISON = 4
LAYOUT_TITLE_ONLY = 5


def set_text(shape, text, font_size=18, bold=False, color=None, alignment=None):
    """Set text on a shape's text frame, clearing existing content."""
    tf = shape.text_frame
    tf.clear()
    p = tf.paragraphs[0]
    p.text = text
    run = p.runs[0]
    run.font.size = Pt(font_size)
    run.font.bold = bold
    if color:
        run.font.color.rgb = color
    if alignment:
        p.alignment = alignment


def add_bullet_list(shape, items, font_size=14, color=None, bold_first=False, spacing=Pt(4)):
    """Add a bulleted list to a shape's text frame."""
    tf = shape.text_frame
    tf.clear()
    tf.word_wrap = True

    for i, item in enumerate(items):
        if i == 0:
            p = tf.paragraphs[0]
        else:
            p = tf.add_paragraph()

        p.space_after = spacing
        p.level = 0

        # Handle bold prefix (e.g., "**Bold:** rest of text")
        if bold_first and ": " in item:
            bold_part, rest = item.split(": ", 1)
            run_bold = p.add_run()
            run_bold.text = bold_part + ": "
            run_bold.font.size = Pt(font_size)
            run_bold.font.bold = True
            if color:
                run_bold.font.color.rgb = color
            run_rest = p.add_run()
            run_rest.text = rest
            run_rest.font.size = Pt(font_size)
            run_rest.font.bold = False
            if color:
                run_rest.font.color.rgb = color
        else:
            run = p.add_run()
            run.text = item
            run.font.size = Pt(font_size)
            if color:
                run.font.color.rgb = color


def add_box(slide, left, top, width, height, fill_color, text="", font_size=9,
            font_color=WHITE, border_color=None, bold=False, corner_radius=None):
    """Add a rounded rectangle with text to the slide."""
    shape = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, left, top, width, height
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = fill_color

    if border_color:
        shape.line.color.rgb = border_color
        shape.line.width = Pt(1.5)
    else:
        shape.line.fill.background()

    if text:
        tf = shape.text_frame
        tf.word_wrap = True
        tf.paragraphs[0].alignment = PP_ALIGN.CENTER
        run = tf.paragraphs[0].add_run()
        run.text = text
        run.font.size = Pt(font_size)
        run.font.color.rgb = font_color
        run.font.bold = bold
        tf.auto_size = None
        shape.text_frame.margin_left = Pt(2)
        shape.text_frame.margin_right = Pt(2)
        shape.text_frame.margin_top = Pt(2)
        shape.text_frame.margin_bottom = Pt(2)

    # Adjust corner radius
    if corner_radius is not None:
        shape.adjustments[0] = corner_radius

    return shape


def add_arrow(slide, start_left, start_top, end_left, end_top, color=MED_GRAY, width=Pt(2)):
    """Add a connector arrow between two points."""
    connector = slide.shapes.add_connector(
        1,  # straight connector
        start_left, start_top,
        end_left, end_top
    )
    connector.line.color.rgb = color
    connector.line.width = width
    return connector


def add_notes(slide, text):
    """Add speaker notes to a slide."""
    notes_slide = slide.notes_slide
    tf = notes_slide.notes_text_frame
    tf.text = text


def embed_image(slide, img_path, left, top, width=None, height=None):
    """Embed an image on a slide if the file exists."""
    if img_path.exists():
        kwargs = {"image_file": str(img_path), "left": left, "top": top}
        if width:
            kwargs["width"] = width
        if height:
            kwargs["height"] = height
        return slide.shapes.add_picture(**kwargs)
    else:
        print(f"  WARNING: Image not found: {img_path}")
        return None


# ============================================================
# SLIDE BUILDERS
# ============================================================

def build_slide_01_title(prs):
    """Slide 1: Title Slide"""
    print("  Slide 1: Title")
    slide = prs.slides.add_slide(prs.slide_layouts[LAYOUT_TITLE])

    for shape in slide.placeholders:
        idx = shape.placeholder_format.idx
        if idx == 0:  # Title
            set_text(shape, "Talos CleanRoom", font_size=36, bold=True)
        elif idx == 1:  # Subtitle
            tf = shape.text_frame
            tf.clear()
            p = tf.paragraphs[0]
            p.alignment = PP_ALIGN.CENTER
            run = p.add_run()
            run.text = "An Infrastructure-as-Code Security Platform on Kubernetes"
            run.font.size = Pt(18)
            run.font.italic = True

            p2 = tf.add_paragraph()
            p2.alignment = PP_ALIGN.CENTER
            p2.space_before = Pt(12)
            run2 = p2.add_run()
            run2.text = "William de Marigny  |  St. Mary's University  |  Spring 2026"
            run2.font.size = Pt(14)

    add_notes(slide,
        "Welcome. I'm William de Marigny and today I'll present Talos CleanRoom -- "
        "a platform I built that deploys a full Kubernetes cluster and integrated security "
        "toolchain with a single click, then lets you scan your network for vulnerabilities "
        "and malware. I'll alternate between slides and live demos so you can see the real "
        "system in action. Total time: about 25 minutes."
    )
    return slide


def build_slide_02_problem(prs):
    """Slide 2: The Problem"""
    print("  Slide 2: The Problem")
    slide = prs.slides.add_slide(prs.slide_layouts[LAYOUT_TITLE_CONTENT])

    for shape in slide.placeholders:
        idx = shape.placeholder_format.idx
        if idx == 0:
            set_text(shape, "The Problem", font_size=32, bold=True)
        elif idx == 1:
            add_bullet_list(shape, [
                "Setting up a security scanning environment is complex and time-consuming",
                "OpenVAS, Metasploit, Faraday, and LOKI each need separate installation, "
                "configuration, networking, and maintenance",
                "Manual Kubernetes deployment is error-prone and not reproducible",
                "No single interface to orchestrate scanning across multiple tools",
                "Results are siloed -- no unified reporting, no comparison over time, "
                "no remediation tracking",
                "Security teams spend more time fighting infrastructure than finding vulnerabilities",
            ], font_size=14)

    add_notes(slide,
        "If you wanted to stand up a professional vulnerability management environment "
        "from scratch, you'd need to install and configure at least 4 separate security tools, "
        "deploy a Kubernetes cluster, set up ingress, TLS, storage, GitOps -- and then build "
        "a way to use all of it together.\n\n"
        "There is no turnkey solution that does all of this as Infrastructure-as-Code with "
        "a web interface. That's the gap this project fills."
    )
    return slide


def build_slide_03_solution(prs):
    """Slide 3: The Solution (Two Content)"""
    print("  Slide 3: The Solution")
    slide = prs.slides.add_slide(prs.slide_layouts[LAYOUT_TWO_CONTENT])

    for shape in slide.placeholders:
        idx = shape.placeholder_format.idx
        if idx == 0:
            set_text(shape, "Talos CleanRoom -- The Solution", font_size=28, bold=True)
        elif idx == 1:  # Left content
            tf = shape.text_frame
            tf.clear()
            # Add "What It Does" header
            p = tf.paragraphs[0]
            run = p.add_run()
            run.text = "What It Does"
            run.font.size = Pt(16)
            run.font.bold = True
            run.font.color.rgb = CYAN

            items = [
                "One-click Kubernetes cluster deployment on Proxmox via Terraform + Talos Linux",
                "Integrated security toolchain: Nmap, OpenVAS, Metasploit, LOKI-RS",
                "3 web applications with single sign-on (Portal, Deployment Console, Scanning Console)",
                "GitOps via ArgoCD -- entire platform state managed in Git",
                "Real-time WebSocket progress for all operations",
            ]
            for item in items:
                p = tf.add_paragraph()
                p.space_after = Pt(4)
                run = p.add_run()
                run.text = item
                run.font.size = Pt(12)

        elif idx == 2:  # Right content
            tf = shape.text_frame
            tf.clear()
            p = tf.paragraphs[0]
            run = p.add_run()
            run.text = "Key Numbers"
            run.font.size = Pt(16)
            run.font.bold = True
            run.font.color.rgb = GREEN

            items = [
                "434 commits over ~3.5 months",
                "23-step automated deployment pipeline",
                "4 scanning tools unified in one interface",
                "3 scan profiles + fully customizable",
                "Zero-trust network policies per namespace",
                "PostgreSQL persistence with daily backups",
                "30+ page documentation site with videos",
            ]
            for item in items:
                p = tf.add_paragraph()
                p.space_after = Pt(4)
                run = p.add_run()
                run.text = item
                run.font.size = Pt(12)

    add_notes(slide,
        "The platform does two major things. First, it deploys your entire infrastructure "
        "with one click -- Terraform creates VMs, Talos Linux bootstraps Kubernetes, and "
        "ArgoCD deploys all the security tools automatically.\n\n"
        "Second, it gives you a unified interface to scan, analyze, and track vulnerabilities "
        "across Nmap, OpenVAS, Metasploit, and LOKI-RS.\n\n"
        "434 commits in about 3 and a half months. The deployment pipeline has 23 automated "
        "steps. Let me show you the architecture."
    )
    return slide


def build_slide_04_architecture(prs):
    """Slide 4: Architecture Diagram (Title Only + programmatic shapes)"""
    print("  Slide 4: Architecture Diagram")
    slide = prs.slides.add_slide(prs.slide_layouts[LAYOUT_TITLE_ONLY])

    for shape in slide.placeholders:
        if shape.placeholder_format.idx == 0:
            set_text(shape, "Platform Architecture", font_size=28, bold=True)

    # --- Diagram layout constants ---
    # Slide is 10" x 5.625"
    margin_left = Inches(0.4)
    diagram_top = Inches(1.15)
    full_width = Inches(9.2)

    row_height = Inches(0.40)
    row_gap = Inches(0.08)
    section_gap = Inches(0.15)

    # --- Row 1: Proxmox Cluster ---
    proxmox_top = diagram_top
    add_box(slide, margin_left, proxmox_top, full_width, Inches(0.45),
            PROXMOX_COLOR, "Proxmox Cluster  (4 nodes: pve01-04, 10.83.2.20-23)",
            font_size=12, bold=True, font_color=WHITE)

    # --- Row 2: K8s Cluster (large container) ---
    k8s_top = proxmox_top + Inches(0.45) + section_gap
    k8s_height = Inches(2.55)
    k8s_box = add_box(slide, margin_left + Inches(0.15), k8s_top, full_width - Inches(0.3), k8s_height,
                       RGBColor(0x1E, 0x3A, 0x5F), border_color=K8S_COLOR)

    # K8s label
    add_box(slide, margin_left + Inches(0.3), k8s_top + Inches(0.05), Inches(4.5), Inches(0.35),
            RGBColor(0x1E, 0x3A, 0x5F),
            "Talos Kubernetes Cluster  (VLAN 3: 10.83.3.0/24)",
            font_size=11, bold=True, font_color=CYAN)

    # --- Nodes row ---
    node_top = k8s_top + Inches(0.45)
    node_width = Inches(2.0)
    node_height = Inches(0.38)
    nodes_left = margin_left + Inches(0.5)

    add_box(slide, nodes_left, node_top, node_width, node_height,
            RGBColor(0x2B, 0x4C, 0x7E), "Control Plane (master-01)", font_size=10, bold=True,
            border_color=K8S_COLOR)
    add_box(slide, nodes_left + Inches(2.2), node_top, Inches(2.5), node_height,
            RGBColor(0x2B, 0x4C, 0x7E), "Workers x3 (worker-01..03)", font_size=10, bold=True,
            border_color=K8S_COLOR)
    add_box(slide, nodes_left + Inches(4.9), node_top, Inches(1.8), node_height,
            RGBColor(0x2B, 0x4C, 0x7E), "Ceph RBD Storage", font_size=10, bold=True,
            border_color=K8S_COLOR)
    add_box(slide, nodes_left + Inches(6.9), node_top, Inches(1.4), node_height,
            RGBColor(0x2B, 0x4C, 0x7E), "Pod/Svc CIDRs", font_size=10,
            border_color=K8S_COLOR)

    # --- Infrastructure row ---
    infra_label_top = node_top + node_height + row_gap + Inches(0.02)
    add_box(slide, nodes_left, infra_label_top, Inches(1.6), Inches(0.25),
            RGBColor(0x1E, 0x3A, 0x5F), "Infrastructure Layer", font_size=9, bold=True,
            font_color=LIGHT_GRAY)

    infra_top = infra_label_top + Inches(0.25) + Inches(0.02)
    infra_items = ["MetalLB", "cert-manager", "Traefik", "Ceph CSI", "ArgoCD"]
    box_w = Inches(1.55)
    for i, name in enumerate(infra_items):
        add_box(slide, nodes_left + i * (box_w + Inches(0.1)), infra_top, box_w, row_height,
                INFRA_COLOR, name, font_size=10, font_color=WHITE, bold=True)

    # --- Security Tools row ---
    sec_label_top = infra_top + row_height + row_gap + Inches(0.02)
    add_box(slide, nodes_left, sec_label_top, Inches(1.6), Inches(0.25),
            RGBColor(0x1E, 0x3A, 0x5F), "Security Tools Layer", font_size=9, bold=True,
            font_color=LIGHT_GRAY)

    sec_top = sec_label_top + Inches(0.25) + Inches(0.02)
    sec_items = ["OpenVAS / Greenbone", "Metasploit", "Faraday", "Harbor Registry"]
    sec_box_w = Inches(2.0)
    for i, name in enumerate(sec_items):
        c = SECURITY_COLOR if i < 3 else RGBColor(0x7C, 0x3A, 0xED)
        add_box(slide, nodes_left + i * (sec_box_w + Inches(0.15)), sec_top, sec_box_w, row_height,
                c, name, font_size=10, font_color=WHITE, bold=True)

    # --- Applications row ---
    app_label_top = sec_top + row_height + row_gap + Inches(0.02)
    add_box(slide, nodes_left, app_label_top, Inches(1.6), Inches(0.25),
            RGBColor(0x1E, 0x3A, 0x5F), "Application Layer", font_size=9, bold=True,
            font_color=LIGHT_GRAY)

    app_top = app_label_top + Inches(0.25) + Inches(0.02)
    app_items = [
        ("Scanning Console", APP_COLOR),
        ("Portal (SSO)", APP_COLOR),
        ("CleanRoom DB (PostgreSQL)", RGBColor(0x33, 0x63, 0x91)),
    ]
    app_box_w = Inches(2.65)
    for i, (name, c) in enumerate(app_items):
        add_box(slide, nodes_left + i * (app_box_w + Inches(0.15)), app_top, app_box_w, row_height,
                c, name, font_size=10, font_color=WHITE, bold=True)

    # --- Row 3: LXC Containers (outside K8s cluster) ---
    lxc_top = k8s_top + k8s_height + section_gap
    lxc_width = Inches(3.8)
    add_box(slide, margin_left + Inches(0.5), lxc_top, lxc_width, Inches(0.42),
            LXC_COLOR, "Deployment Console (LXC, 10.83.3.190)",
            font_size=10, bold=True, font_color=WHITE)
    add_box(slide, margin_left + Inches(0.5) + lxc_width + Inches(0.3), lxc_top, lxc_width, Inches(0.42),
            LXC_COLOR, "Build VM -- Docker Image Builds (LXC, 10.83.3.191)",
            font_size=10, bold=True, font_color=WHITE)

    # --- Ingress path annotation ---
    anno_top = lxc_top + Inches(0.55)
    txBox = slide.shapes.add_textbox(margin_left + Inches(0.3), anno_top, Inches(9.0), Inches(0.30))
    tf = txBox.text_frame
    tf.word_wrap = True
    p = tf.paragraphs[0]
    p.alignment = PP_ALIGN.CENTER
    run = p.add_run()
    run.text = "Ingress: Internet  \u2192  MetalLB (10.83.3.200)  \u2192  Traefik  \u2192  K8s Services   |   DNS: *.knowledgeondemand.net   |   TLS: Wildcard cert (Cloudflare DNS-01)"
    run.font.size = Pt(9)
    run.font.color.rgb = MED_GRAY
    run.font.italic = True

    add_notes(slide,
        "The foundation is a 4-node Proxmox cluster. Terraform creates 4 VMs that become a "
        "Talos Linux Kubernetes cluster -- one control plane and three workers.\n\n"
        "Inside the cluster, ArgoCD manages everything via GitOps. The infrastructure layer "
        "handles load balancing (MetalLB), TLS certificates (cert-manager), and ingress (Traefik). "
        "The security layer runs OpenVAS, Metasploit, Faraday, and Harbor as containerized workloads.\n\n"
        "The Scanning Console and Portal run inside the cluster. The Deployment Console runs in a "
        "separate LXC container because it needs to manage the cluster from outside.\n\n"
        "Every namespace has default-deny network policies -- zero-trust networking."
    )
    return slide


def build_slide_05_tech_stack(prs):
    """Slide 5: Technology Stack (Comparison layout)"""
    print("  Slide 5: Tech Stack")
    slide = prs.slides.add_slide(prs.slide_layouts[LAYOUT_COMPARISON])

    for shape in slide.placeholders:
        idx = shape.placeholder_format.idx
        if idx == 0:
            set_text(shape, "Technology Stack", font_size=28, bold=True)
        elif idx == 1:  # Left label
            set_text(shape, "Backend & Infrastructure", font_size=14, bold=True, color=CYAN)
        elif idx == 2:  # Left content
            add_bullet_list(shape, [
                "Python / FastAPI + Uvicorn (async)",
                "PostgreSQL 17 (SQLAlchemy + Alembic)",
                "Terraform (Proxmox VM provisioning)",
                "Talos Linux (immutable Kubernetes OS)",
                "ArgoCD (GitOps, self-healing, auto-sync)",
                "SOPS + Age (secret encryption in Git)",
                "Ceph RBD (persistent block storage)",
            ], font_size=12)
        elif idx == 3:  # Right label
            set_text(shape, "Frontend & Security Tools", font_size=14, bold=True, color=GREEN)
        elif idx == 4:  # Right content
            add_bullet_list(shape, [
                "Jinja2 + Alpine.js + Tailwind CSS",
                "WebSocket + REST polling fallback",
                "JWT SSO with HMAC one-time codes",
                "Nmap (port & service discovery)",
                "OpenVAS / Greenbone (70k+ vuln tests)",
                "Metasploit (exploit verification)",
                "LOKI-RS (IOC / malware scanning)",
                "Faraday (vuln management aggregation)",
            ], font_size=12)

    add_notes(slide,
        "On the backend, all three web apps use FastAPI, a modern async Python framework. "
        "The frontend uses server-rendered Jinja2 templates with Alpine.js for interactivity "
        "and Tailwind CSS for styling.\n\n"
        "I chose Talos Linux because it's an immutable, API-driven OS designed for Kubernetes "
        "-- no SSH, no shell, no package manager. Inherently more secure.\n\n"
        "Cross-app authentication uses HMAC-signed one-time codes so the user logs in once "
        "at the Portal and is seamlessly authenticated across all three apps.\n\n"
        "TRANSITION: Let me switch to the live system and show you how this works in practice."
    )
    return slide


def build_slide_06_demo_transition_1(prs):
    """Slide 6: Live Demo Transition 1 (Section Header)"""
    print("  Slide 6: Demo Transition 1")
    slide = prs.slides.add_slide(prs.slide_layouts[LAYOUT_SECTION])

    for shape in slide.placeholders:
        idx = shape.placeholder_format.idx
        if idx == 0:  # Title (bottom in section header)
            set_text(shape, "Live Demo", font_size=36, bold=True)
        elif idx == 1:  # Body text (top in section header)
            set_text(shape, "Portal Login  \u2192  SSO Navigation  \u2192  Deployment Console  \u2192  "
                     "Dashboard  \u2192  Configuration", font_size=16)

    add_notes(slide,
        "TRANSITION TO LIVE DEMO.\n\n"
        "Switch to browser. Tabs should be pre-loaded.\n\n"
        "Demo flow (5 minutes):\n"
        "1. Portal login (30s): Open cleanroom.knowledgeondemand.net, log in admin/admin, "
        "show landing page with two console cards\n"
        "2. SSO navigation (30s): Click Deployment Console card, point out no second login needed\n"
        "3. Dashboard (1m): Show completed deployment, scroll through 23 steps, show service links\n"
        "4. Configuration (1m): Show Terraform config, Talos config, trigger validation error\n"
        "5. Logs (1m): Show log filtering, historical logs, failed/resume/skip capability\n"
        "6. Cleanup (30s): Show cleanup dialog but do NOT click confirm\n\n"
        "FALLBACK: If demo fails, play 01-getting-started.mp4 (37s) and narrate over screenshots."
    )
    return slide


def build_slide_07_deployment_pipeline(prs):
    """Slide 7: 23-Step Deployment Pipeline"""
    print("  Slide 7: Deployment Pipeline")
    slide = prs.slides.add_slide(prs.slide_layouts[LAYOUT_TITLE_CONTENT])

    for shape in slide.placeholders:
        idx = shape.placeholder_format.idx
        if idx == 0:
            set_text(shape, "23-Step Automated Deployment", font_size=28, bold=True)
        elif idx == 1:
            add_bullet_list(shape, [
                "Steps 0-2: Terraform VM creation on Proxmox (4 VMs)",
                "Steps 3-5: Talos config generation, application, cluster bootstrap",
                "Steps 6-8: Health verification, kubeconfig retrieval, ArgoCD installation",
                "Steps 9-11: Infrastructure stack (MetalLB, cert-manager, Traefik, Ceph)",
                "Steps 12-16: ArgoCD self-management, security tools (OpenVAS, Faraday, "
                "Metasploit, Harbor)",
                "Steps 17-22: Secrets, Build VM, container image builds, app deployment, "
                "network policies",
                "",
                "Every step is checkpointed to an encrypted state file",
                "If step 14 fails, resume from step 14 -- all previous work is preserved",
                "Real-time WebSocket progress; automatic REST polling fallback",
            ], font_size=13, bold_first=False)

    # Embed screenshot inset (use wide config screenshot; deployment screenshots are tall scrolls)
    img_path = IMG_DIR / "deployment" / "deployment-config-terraform.jpg"
    embed_image(slide, img_path, Inches(5.8), Inches(3.0), width=Inches(3.8), height=Inches(2.4))

    add_notes(slide,
        "What you just saw in the demo was the end state. Here's what actually happens during "
        "a deployment.\n\n"
        "The 23 steps cover everything from VM creation through network policy enforcement. "
        "Every step is checkpointed to a Fernet-encrypted state file. If any step fails, "
        "you can fix the issue and resume from that exact step.\n\n"
        "The deployment page uses WebSockets to stream progress in real time. If the WebSocket "
        "connection drops, it automatically falls back to REST polling."
    )
    return slide


def build_slide_08_scanning(prs):
    """Slide 8: Scanning Architecture (Two Content)"""
    print("  Slide 8: Scanning Architecture")
    slide = prs.slides.add_slide(prs.slide_layouts[LAYOUT_TWO_CONTENT])

    for shape in slide.placeholders:
        idx = shape.placeholder_format.idx
        if idx == 0:
            set_text(shape, "Scanning Console -- Unified Vulnerability Management",
                     font_size=24, bold=True)
        elif idx == 1:  # Left
            tf = shape.text_frame
            tf.clear()
            p = tf.paragraphs[0]
            run = p.add_run()
            run.text = "Vulnerability Scanning"
            run.font.size = Pt(15)
            run.font.bold = True
            run.font.color.rgb = CYAN

            items = [
                "Nmap: port discovery & service fingerprinting",
                "OpenVAS: 70,000+ vulnerability tests (NVTs)",
                "Metasploit: exploit-based verification (11-39 modules)",
                "Results auto-enriched with CVSS + EPSS scores",
                "All findings aggregated in Faraday",
                "3 profiles: Quick (5-15m), Standard (15-45m), Thorough (1-3h)",
            ]
            for item in items:
                p = tf.add_paragraph()
                p.space_after = Pt(3)
                run = p.add_run()
                run.text = item
                run.font.size = Pt(11)

        elif idx == 2:  # Right
            tf = shape.text_frame
            tf.clear()
            p = tf.paragraphs[0]
            run = p.add_run()
            run.text = "IOC Scanning"
            run.font.size = Pt(15)
            run.font.bold = True
            run.font.color.rgb = GREEN

            items = [
                "LOKI-RS: file-based indicator of compromise scanner",
                "Mounts remote filesystems via SSH or SMB/CIFS",
                "Scans against YARA rules, malicious hashes, threat signatures",
                "Severity levels: Alert (80+), Warning (60-79), Notice (<60)",
                "Runs as ephemeral privileged K8s pods",
                "Findings persisted to PostgreSQL + uploaded to Faraday",
            ]
            for item in items:
                p = tf.add_paragraph()
                p.space_after = Pt(3)
                run = p.add_run()
                run.text = item
                run.font.size = Pt(11)

    add_notes(slide,
        "The Scanning Console provides a unified interface across four vulnerability scanning "
        "tools and one IOC scanner.\n\n"
        "You pick a target, select tools, choose a scan profile, and click Start. The system "
        "orchestrates tools in parallel, streams progress via WebSocket, enriches results with "
        "CVSS severity and EPSS exploit probability scores, and uploads everything to Faraday.\n\n"
        "The IOC scanner checks individual servers for malware by mounting their filesystem "
        "and running LOKI-RS against known threat signatures. Useful for incident response.\n\n"
        "TRANSITION: Let me demonstrate the scanning workflow live."
    )
    return slide


def build_slide_09_demo_transition_2(prs):
    """Slide 9: Live Demo Transition 2 (Section Header)"""
    print("  Slide 9: Demo Transition 2")
    slide = prs.slides.add_slide(prs.slide_layouts[LAYOUT_SECTION])

    for shape in slide.placeholders:
        idx = shape.placeholder_format.idx
        if idx == 0:
            set_text(shape, "Live Demo", font_size=36, bold=True)
        elif idx == 1:
            set_text(shape, "Vulnerability Scan  \u2192  IOC Scan  \u2192  Reports Dashboard  \u2192  "
                     "Scan Comparison", font_size=16)

    add_notes(slide,
        "TRANSITION TO LIVE DEMO 2.\n\n"
        "Demo flow (8 minutes):\n"
        "1. SSO into Scanning Console (15s): Click card from Portal\n"
        "2. Target Lab (1.5m): Show Vulhub catalog, active targets\n"
        "3. Vulnerability scan config (1m): Enter target, select Nmap+OpenVAS, Quick profile, "
        "show Custom module picker, start scan\n"
        "4. Scan progress (1.5m): Show real-time tool progress cards, log filtering by tool. "
        "If Nmap finishes, show completion. If OpenVAS still running, explain and move on.\n"
        "5. IOC Scanning (1.5m): Show SSH/SMB config, start scan if target available, show findings\n"
        "6. Reports (2m): Dashboard summary, drill into scan detail, hosts view, vulnerability "
        "filters, scan comparison, audit log, remediation tracking\n\n"
        "FALLBACK: Play 05-reports-tour.mp4 (35s) for reports. Show screenshots in sequence."
    )
    return slide


def build_slide_10_security(prs):
    """Slide 10: Security Architecture"""
    print("  Slide 10: Security Architecture")
    slide = prs.slides.add_slide(prs.slide_layouts[LAYOUT_TITLE_CONTENT])

    for shape in slide.placeholders:
        idx = shape.placeholder_format.idx
        if idx == 0:
            set_text(shape, "Security Architecture & Design Decisions", font_size=26, bold=True)
        elif idx == 1:
            add_bullet_list(shape, [
                "Immutable OS: Talos Linux -- no SSH, no shell, no package manager; API-only management",
                "Zero-trust networking: Default-deny network policies per namespace; explicit allow-lists",
                "Secret management: SOPS + Age encryption; secrets never stored in plaintext in Git",
                "Cross-domain SSO: HMAC-signed one-time codes (no JWT in URLs, single-use, rate-limited)",
                "Container security: Private Harbor registry with Trivy vulnerability scanning on push",
                "Database security: Alembic migrations via hardened init container (non-root, read-only FS)",
                "Fault tolerance: Deployment checkpointed per step; WebSocket with REST fallback",
                "Key derivation: Single SECRET_KEY derives separate keys for JWT, HMAC, and Fernet",
            ], font_size=13, bold_first=True)

    add_notes(slide,
        "Security was a primary concern throughout the design.\n\n"
        "Starting at the OS level, Talos Linux is immutable -- you literally cannot SSH into "
        "the nodes. The only way to manage them is through the Talos API.\n\n"
        "At the network level, every namespace starts with default-deny for both ingress and "
        "egress. I had to explicitly define what each service is allowed to talk to.\n\n"
        "Secrets are encrypted at rest in the Git repository using SOPS with Age keys. "
        "ArgoCD decrypts them on deploy via the KSOPS plugin.\n\n"
        "The SSO mechanism avoids putting JWTs in URLs (a common security anti-pattern). "
        "Instead, the Portal generates a short-lived HMAC-signed one-time code that the "
        "target app exchanges for a local JWT."
    )
    return slide


def build_slide_11_results(prs):
    """Slide 11: Results & Achievements"""
    print("  Slide 11: Results")
    slide = prs.slides.add_slide(prs.slide_layouts[LAYOUT_TITLE_CONTENT])

    for shape in slide.placeholders:
        idx = shape.placeholder_format.idx
        if idx == 0:
            set_text(shape, "Results & Achievements", font_size=28, bold=True)
        elif idx == 1:
            add_bullet_list(shape, [
                "Fully automated: bare Proxmox nodes to running security platform in ~45 minutes",
                "3 production-quality web applications with shared authentication library",
                "Comprehensive documentation: 30+ page MkDocs site with screenshots and video walkthroughs",
                "434 commits across 3.5 months of development",
                "Technology breadth: Python, JavaScript, Bash, Terraform HCL, Kubernetes YAML, Helm, SQL",
                "Successfully scanned targets and detected known CVEs with all four scanning tools",
                "Demonstrated IOC detection capability against simulated threat indicators",
                "All infrastructure reproducible from Git -- true Infrastructure-as-Code",
            ], font_size=13)

    # Embed reports dashboard screenshot (1.60 aspect ratio - wide)
    img_path = IMG_DIR / "reports" / "reports-dashboard.jpg"
    embed_image(slide, img_path, Inches(5.8), Inches(2.8), width=Inches(3.8), height=Inches(2.4))

    add_notes(slide,
        "The end result is a platform that takes bare Proxmox nodes and, with one click, "
        "produces a fully operational Kubernetes cluster running a complete security toolchain.\n\n"
        "I wrote over 430 commits of code across Python, JavaScript, Bash, Terraform, and "
        "Kubernetes manifests. The three web applications share a common library.\n\n"
        "The documentation site has over 30 pages with screenshots and video walkthroughs."
    )
    return slide


def build_slide_12_lessons(prs):
    """Slide 12: Lessons Learned & Future Work (Comparison layout)"""
    print("  Slide 12: Lessons & Future")
    slide = prs.slides.add_slide(prs.slide_layouts[LAYOUT_COMPARISON])

    for shape in slide.placeholders:
        idx = shape.placeholder_format.idx
        if idx == 0:
            set_text(shape, "Lessons Learned & Future Work", font_size=26, bold=True)
        elif idx == 1:  # Left label
            set_text(shape, "Lessons Learned", font_size=14, bold=True, color=YELLOW)
        elif idx == 2:  # Left content
            add_bullet_list(shape, [
                "OpenVAS resource tuning: OOMKill at 1Gi, needed 4Gi (trial and error)",
                "Faraday Community Edition: no bulk API; had to create findings individually",
                "LOKI-RS in K8s: needed privileged pods + FUSE for filesystem mounting",
                "kubectl output truncation: SPDY ~200KB limit; temp files + base64 workaround",
                "Cross-app auth: built 3 iterations before one-time code exchange",
            ], font_size=11)
        elif idx == 3:  # Right label
            set_text(shape, "Future Work", font_size=14, bold=True, color=CYAN)
        elif idx == 4:  # Right content
            add_bullet_list(shape, [
                "Scheduled / recurring scans (cron-based)",
                "LDAP / Active Directory authentication",
                "Multi-cluster support",
                "Dashboard analytics with trend graphs",
                "SecureCodeBox integration for CI/CD scanning",
                "Automated remediation workflows",
            ], font_size=11)

    add_notes(slide,
        "Some highlights from lessons learned:\n\n"
        "OpenVAS kept getting killed by Kubernetes because it exceeded its memory limit. "
        "The default 1Gi was not enough; I had to bump it to 4Gi and enable shared process "
        "namespaces for zombie process reaping.\n\n"
        "Faraday's Community Edition doesn't have a bulk API -- the Celery worker that processes "
        "bulk imports doesn't run. I had to write code to create hosts, services, and "
        "vulnerabilities individually via the REST API.\n\n"
        "For future work, the most impactful addition would be scheduled scans so security "
        "teams don't have to manually trigger scans."
    )
    return slide


def build_slide_13_questions(prs):
    """Slide 13: Questions"""
    print("  Slide 13: Questions")
    slide = prs.slides.add_slide(prs.slide_layouts[LAYOUT_TITLE])

    for shape in slide.placeholders:
        idx = shape.placeholder_format.idx
        if idx == 0:
            set_text(shape, "Questions?", font_size=40, bold=True)
        elif idx == 1:
            tf = shape.text_frame
            tf.clear()
            p = tf.paragraphs[0]
            p.alignment = PP_ALIGN.CENTER
            run = p.add_run()
            run.text = "William de Marigny"
            run.font.size = Pt(18)

            p2 = tf.add_paragraph()
            p2.alignment = PP_ALIGN.CENTER
            p2.space_before = Pt(8)
            run2 = p2.add_run()
            run2.text = "github.com/williamdemarigny/Talos-CleanRoom"
            run2.font.size = Pt(14)

    add_notes(slide,
        "Thank you for your attention. Happy to take questions.\n\n"
        "Have the live system still open in the browser in case someone asks to see a feature.\n\n"
        "Anticipated questions:\n"
        "- Why Talos Linux? Immutable, API-only, no attack surface from SSH/shell.\n"
        "- Why not managed K8s? Runs on-premises on Proxmox for full control.\n"
        "- How long does deployment take? About 45 minutes from bare nodes.\n"
        "- Could this scale to production? Yes -- Talos and ArgoCD are production-grade."
    )
    return slide


# ============================================================
# MAIN
# ============================================================

def main():
    print(f"Loading template: {TEMPLATE_PATH}")
    prs = Presentation(str(TEMPLATE_PATH))

    # Remove existing sample slides (4 slides in the template)
    print("Removing template sample slides...")
    while len(prs.slides) > 0:
        rId = prs.slides._sldIdLst[0].get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')
        if rId is None:
            # Try the 'id' attribute directly
            slide_id = prs.slides._sldIdLst[0]
            prs.part.drop_rel(slide_id.rId)
            prs.slides._sldIdLst.remove(slide_id)
        else:
            prs.part.drop_rel(rId)
            prs.slides._sldIdLst.remove(prs.slides._sldIdLst[0])

    print("Building slides...")
    build_slide_01_title(prs)
    build_slide_02_problem(prs)
    build_slide_03_solution(prs)
    build_slide_04_architecture(prs)
    build_slide_05_tech_stack(prs)
    build_slide_06_demo_transition_1(prs)
    build_slide_07_deployment_pipeline(prs)
    build_slide_08_scanning(prs)
    build_slide_09_demo_transition_2(prs)
    build_slide_10_security(prs)
    build_slide_11_results(prs)
    build_slide_12_lessons(prs)
    build_slide_13_questions(prs)

    print(f"\nSaving to: {OUTPUT_PATH}")
    prs.save(str(OUTPUT_PATH))
    print(f"Done! {len(prs.slides)} slides created.")


if __name__ == "__main__":
    main()

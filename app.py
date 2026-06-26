import streamlit as st
import cv2
import time
import qrcode
from io import BytesIO
from datetime import datetime
from PIL import Image
from ultralytics import YOLO
from twilio.rest import Client
from reportlab.lib.pagesizes import A4
from reportlab.pdfgen import canvas
import os

# ─── Page & Style Setup ───────────────────────────────────────────────────────
st.set_page_config(page_title="Smart Billing System 💳",
                   page_icon="🛍️", layout="centered")

st.markdown("""
<style>
.stButton > button {
    background-color: #2ecc71;
    color: white;
    padding: 0.6em 1.2em;
    font-size: 1em;
    border-radius: 8px;
    margin: 5px;
}
.stButton > button:hover {
    background-color: #27ae60;
}
</style>
""", unsafe_allow_html=True)

st.markdown("""
<h1 style='text-align: center; color: #2e9aff;'>
    🧾 Smart Billing System
</h1>
<hr style="border-top: 1px solid #bbb;">
""", unsafe_allow_html=True)

# ─── PDF Generation Function ─────────────────────────────────────────────────
def generate_invoice_pdf(filename, items, total):
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    c = canvas.Canvas(filename, pagesize=A4)
    w, h = A4

    c.setFont("Helvetica-Bold", 18)
    c.drawString(50, h - 50, "Smart Billing Invoice 🧾")

    c.setFont("Helvetica", 12)
    c.drawString(50, h - 80, f"Date: {now}")
    c.drawString(50, h - 100, f"Mobile: +91 {st.session_state.phone_number}")

    y = h - 140
    c.setFont("Helvetica-Bold", 12)
    for lbl, x in zip(["Item", "Quantity", "Price", "Subtotal"], [50, 250, 350, 450]):
        c.drawString(x, y, lbl)
    c.setFont("Helvetica", 12)
    y -= 20
    for it, cnt in items.items():
        pr = item_prices.get(it, 0)
        stl = pr * cnt
        c.drawString(50, y, it)
        c.drawString(250, y, str(cnt))
        c.drawString(350, y, f"₹{pr}")
        c.drawString(450, y, f"₹{stl}")
        y -= 20

    y -= 10
    c.setFont("Helvetica-Bold", 14)
    c.drawString(50, y, f"Total: ₹{total}")

    # Payment method
    y -= 30
    c.setFont("Helvetica", 12)
    pm = st.session_state.get("payment_method", "Not Specified")
    c.drawString(50, y, f"Payment Method: {pm}")

    # Paid label
    y -= 40
    c.setFont("Helvetica-Bold", 20)
    c.setFillColorRGB(0, 0.6, 0)  # green
    c.drawString(50, y, "✔️ PAID")

    c.save()

# ─── Load Model & Config ───────────────────────────────────────────────────────
model = YOLO("runs/detect/train/weights/best.pt")

TWILIO_SID         = "AC337308f3f5e267c8fe9c8f857fab95ec"
TWILIO_AUTH_TOKEN  = "4fae44e049033f5c4b89c40895ee4708"
TWILIO_PHONE_NUMBER= "+16672880864"

item_prices = {
    "milo-180ml": 20,
    "slice-200ml": 25,
    "lays-large": 50
}

# ─── Session State Initialization ─────────────────────────────────────────────
defaults = {
    "detected_items": {},
    "scanning": False,
    "stopped": False,
    "phone_entered": False,
    "phone_number": "",
    "start_new_bill": False,
    "payment_method": "",
    "payment_confirmed": False
}
for k, v in defaults.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ─── Reset Flow for New Bill ─────────────────────────────────────────────────
if st.session_state.start_new_bill:
    for k in defaults:
        st.session_state[k] = defaults[k]
    st.rerun()

# ─── Phone Entry Screen ───────────────────────────────────────────────────────
if not st.session_state.phone_entered:
    st.title("📲 Welcome to Smart Billing")
    st.session_state.phone_number = st.text_input(
        "Enter your mobile number:", max_chars=10, key="phone_input"
    )
    if st.button("Proceed"):
        if len(st.session_state.phone_number)==10 and st.session_state.phone_number.isdigit():
            st.session_state.phone_entered = True
        else:
            st.warning("⚠️ Please enter a valid 10-digit mobile number.")
    st.stop()

# ─── Main Billing UI ──────────────────────────────────────────────────────────

col1, col2, col3 = st.columns(3)
with col1:
    if st.button("📸 Start Scanning"):
        st.session_state.scanning = True
        st.session_state.stopped  = False
        st.session_state.detected_items = {}
with col2:
    if st.button("🔄 Reset"):
        st.session_state.detected_items = {}
        st.session_state.stopped = False
with col3:
    if st.button("⛔ Stop"):
        st.session_state.scanning = False
        st.session_state.stopped = True

bill_placeholder = st.empty()

def display_bill(editable=False):
    total = 0
    with bill_placeholder.container():
        st.markdown("### 🛍️ Current Bill")
        for item, count in st.session_state.detected_items.copy().items():
            price    = item_prices.get(item, 0)
            subtotal = price * count
            total   += subtotal
            c1, c2, c3 = st.columns([4,1,1])
            c1.markdown(f"**{item}** – ₹{price} × {count} = ₹{subtotal}")
            if editable:
                if c2.button("➕", key=f"plus_{item}"):
                    st.session_state.detected_items[item] += 1
                if c3.button("➖", key=f"minus_{item}"):
                    if st.session_state.detected_items[item]>1:
                        st.session_state.detected_items[item] -= 1
                    else:
                        del st.session_state.detected_items[item]
        st.markdown(f"### 💰 Total: ₹{total}")
    return total

# ─── Detection Loop ───────────────────────────────────────────────────────────
if st.session_state.scanning:
    cap   = cv2.VideoCapture(0)
    frame = st.empty()
    while st.session_state.scanning:
        ok, img = cap.read()
        if not ok:
            st.error("⚠️ Cannot access camera.")
            break
        results = model.predict(img, conf=0.5)[0]
        for box in results.boxes.data.tolist():
            cls = results.names[int(box[5])]
            if cls not in st.session_state.detected_items:
                st.session_state.detected_items[cls] = 1
        frame.image(results.plot(), channels="BGR")
        display_bill()
        time.sleep(0.2)
    cap.release()

# ─── Final Bill, Payment & SMS ────────────────────────────────────────────────
if st.session_state.stopped and st.session_state.detected_items:
    st.markdown("---")
    st.markdown("## ✅ Final Bill")
    total = display_bill(editable=True)

    # Payment Method
    st.markdown("💳 Choose Payment Method")
    pm = st.radio("", ["Pay at Counter", "Pay Here (Online)"], key="payment_radio")
    st.session_state.payment_method = pm
    if pm=="Pay Here (Online)":
        st.image("698ba34b-2b22-41ba-9ce5-52b57b1d9639.png",
                 width=300, caption="Scan to pay with any UPI app")
        st.success("📲 Please scan to complete payment.")
    else:
        st.info("🏪 Please proceed to the counter to complete payment.")

    # Confirm Payment
    if st.button("💰 Confirm Payment"):
        st.session_state.payment_confirmed = True
        st.success("✔️ Payment Confirmed!")

    # Send SMS
    if st.session_state.payment_confirmed and st.button("Next ➡️ Send Invoice"):
        now  = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        body = f"Bill Invoice date: {now}\nThank you for shopping with us\nItems:\n"
        for it, c in st.session_state.detected_items.items():
            body += f"{it} - {c} pcs\n"
        body += f"Total: ₹{total}"
        try:
            Client(TWILIO_SID, TWILIO_AUTH_TOKEN).messages.create(
                body=body,
                from_=TWILIO_PHONE_NUMBER,
                to=f"+91{st.session_state.phone_number}"
            )
            st.success("✅ Invoice sent via SMS!")
        except:
            st.error("❌ SMS failed. Check Twilio console.")

    # Download PDF
    if st.session_state.payment_confirmed and st.button("🖨️ Download PDF Invoice"):
        pdf_name = f"Invoice_{datetime.now():%Y%m%d_%H%M%S}.pdf"
        generate_invoice_pdf(pdf_name,
                             st.session_state.detected_items,
                             total)
        with open(pdf_name, "rb") as f:
            st.download_button("📄 Download Invoice",
                               data=f, file_name=pdf_name,
                               mime="application/pdf")
        os.remove(pdf_name)

    # Start New Bill
    st.markdown("---")
    if st.button("🧾 Start New Bill"):
        st.session_state.start_new_bill = True
        st.rerun()

# ─── Footer with Links & QR ──────────────────────────────────────────────────
linkedin_url = "https://www.linkedin.com/in/pawan-bhatia-5a119b274/"
github_url   = "https://github.com/pawanbhatia1304/Smart-Billing-AI.git"
email_addr   = "pawanbhatia1304@gmail.com"

# Generate QR
qr = qrcode.make(github_url)
buf = BytesIO()
qr.save(buf, format="PNG")
buf.seek(0)
qr_img = Image.open(buf)

st.markdown("<hr>", unsafe_allow_html=True)
cols = st.columns([2,1,2])
with cols[0]:
    st.image(qr_img, width=100, caption="Smart Billing Github")
with cols[1]:
    st.markdown(f"""
        <div style='text-align:center; color:white; font-size:0.9em;'>
            <strong>SmartBillingAI</strong><br>
            <a href="{github_url}" target="_blank">GitHub</a><br>
            <a href="{linkedin_url}" target="_blank">LinkedIn</a><br>
            {email_addr}
        </div>
    """, unsafe_allow_html=True)
with cols[2]:
    st.write("")  # spacer


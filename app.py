
import streamlit as st
import pdfplumber
import pandas as pd
import re
import hashlib
import io
from datetime import datetime

st.set_page_config(page_title="InvoiceFlow AI", page_icon="🧾", layout="wide")
st.title("🧾 InvoiceFlow AI")
st.caption("Automated invoice extraction, purchase-order matching and exception detection")

if "history" not in st.session_state:
    st.session_state.history = []

purchase_orders = pd.DataFrame([
    {"PO Number": "PO-1001", "Vendor": "ABC Technologies", "Amount": 50000.0},
    {"PO Number": "PO-1002", "Vendor": "Tech Solutions", "Amount": 75000.0},
])

with st.sidebar:
    st.header("Workflow settings")
    tolerance = st.number_input("Amount tolerance (₹)", min_value=0.0, value=0.0, step=500.0)
    st.caption("Differences above this amount are flagged for review.")
    st.subheader("Purchase orders")
    st.dataframe(purchase_orders, hide_index=True, use_container_width=True)

def extract_invoice(pdf_bytes):
    with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
        text = "\n".join(page.extract_text() or "" for page in pdf.pages)

    def get(pattern):
        match = re.search(pattern, text, re.I | re.M)
        return match.group(1).strip() if match else ""

    invoice_no = get(r"Invoice\s*(?:Number|No\.?)\s*[:#]?\s*([A-Z0-9-]+)")
    vendor = get(r"Vendor\s*[:#]?\s*(.+)")
    po_no = get(r"(?:Purchase\s+Order|PO(?:\s*(?:Number|No\.?))?)\s*[:#]?\s*(PO-[A-Z0-9-]+)")
    total_raw = get(r"(?:Grand\s*)?Total(?:\s+Amount)?\s*[:₹ ]*\s*(?:INR|Rs\.?|₹)?\s*([0-9,]+(?:\.\d{1,2})?)")
    currency = get(r"Currency\s*[:#]?\s*([A-Z]{3})") or "INR"

    try:
        total = float(total_raw.replace(",", "")) if total_raw else None
    except ValueError:
        total = None

    return {
        "invoice_no": invoice_no, "vendor": vendor, "po_no": po_no,
        "total": total, "currency": currency, "raw_text": text
    }

def validate_invoice(data, tolerance):
    issues = []
    if not data["invoice_no"]:
        issues.append("Missing invoice number")
    if not data["vendor"]:
        issues.append("Missing vendor name")
    if not data["po_no"]:
        issues.append("Missing purchase-order number")
    if data["total"] is None:
        issues.append("Missing or unreadable invoice total")
    elif data["total"] < 0:
        issues.append("Invoice total cannot be negative")

    if data["currency"] != "INR":
        issues.append(f"Currency requires review: {data['currency']}")

    po = purchase_orders[purchase_orders["PO Number"] == data["po_no"]]
    if data["po_no"] and po.empty:
        issues.append("Purchase order not found")

    if not po.empty:
        expected = po.iloc[0]
        if data["vendor"] and data["vendor"].casefold() != expected["Vendor"].casefold():
            issues.append("Vendor does not match purchase order")
        if data["total"] is not None and data["total"] >= 0:
            difference = abs(data["total"] - float(expected["Amount"]))
            if difference > tolerance:
                issues.append(
                    f"Amount mismatch: invoice ₹{data['total']:,.2f}, "
                    f"PO ₹{expected['Amount']:,.2f}, difference ₹{difference:,.2f}"
                )

    return ("NEEDS_REVIEW", issues) if issues else (
        "ELIGIBLE_FOR_APPROVAL", ["All configured checks passed"]
    )

uploaded = st.file_uploader("Upload invoice PDF", type=["pdf"])

if uploaded:
    pdf_bytes = uploaded.getvalue()
    file_hash = hashlib.sha256(pdf_bytes).hexdigest()

    try:
        data = extract_invoice(pdf_bytes)
        existing_invoice = next(
            (row for row in st.session_state.history
             if data["invoice_no"]
             and row["Invoice Number"] == data["invoice_no"]),
            None
        )

        status, issues = validate_invoice(data, tolerance)
        if existing_invoice:
            status = "DUPLICATE"
            issues = ["Invoice number has already been processed"]

        if not any(row["File Hash"] == file_hash for row in st.session_state.history):
            st.session_state.history.append({
                "Invoice Number": data["invoice_no"] or "Unknown",
                "Vendor": data["vendor"] or "Unknown",
                "PO Number": data["po_no"] or "Unknown",
                "Total (₹)": data["total"],
                "Status": status,
                "Issues": "; ".join(issues),
                "File Hash": file_hash,
                "Processed At": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            })

        st.subheader("Extracted invoice details")
        c1, c2, c3 = st.columns(3)
        c1.metric("Invoice number", data["invoice_no"] or "Not found")
        c2.metric("Purchase order", data["po_no"] or "Not found")
        c3.metric("Invoice total", f"₹{data['total']:,.2f}" if data["total"] is not None else "Not found")
        st.write("**Vendor:**", data["vendor"] or "Not found")
        st.write("**Currency:**", data["currency"])

        st.subheader("Validation result")
        if status == "ELIGIBLE_FOR_APPROVAL":
            st.success(status)
        elif status == "DUPLICATE":
            st.error(status)
        else:
            st.warning(status)

        for issue in issues:
            st.write("•", issue)

        with st.expander("View extracted PDF text"):
            st.text(data["raw_text"])

    except Exception as exc:
        st.error(f"Could not process this PDF: {exc}")

st.divider()
st.subheader("Processing history")

if st.session_state.history:
    history = pd.DataFrame(st.session_state.history)
    st.dataframe(history.drop(columns=["File Hash"]), hide_index=True, use_container_width=True)
    c1, c2, c3 = st.columns(3)
    c1.metric("Processed invoices", len(history))
    c2.metric("Eligible", int((history["Status"] == "ELIGIBLE_FOR_APPROVAL").sum()))
    c3.metric("Flagged", int((history["Status"] != "ELIGIBLE_FOR_APPROVAL").sum()))
    csv = history.drop(columns=["File Hash"]).to_csv(index=False).encode("utf-8")
    st.download_button("Download history CSV", csv, "invoice_history.csv", "text/csv")
else:
    st.info("Upload an invoice PDF to begin.")

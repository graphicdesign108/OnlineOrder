
import re
import pandas as pd
import streamlit as st

st.set_page_config(page_title="Sales Pattern Dashboard V7", layout="wide")

# ----------------------------
# Utilities
# ----------------------------
def normalize_col(col):
    col = str(col).strip().lower()
    col = re.sub(r"[\n\r\t]+", " ", col)
    col = re.sub(r"\s+", " ", col)
    return col

def find_col(df, aliases):
    norm_map = {normalize_col(c): c for c in df.columns}
    for alias in aliases:
        key = normalize_col(alias)
        if key in norm_map:
            return norm_map[key]
    return None

def auto_map_columns(df, alias_map):
    return dict((std, find_col(df, aliases)) for std, aliases in alias_map.items())

def safe_str_series(series):
    return series.astype(str).replace("nan", "").fillna("").str.strip()

def format_int(x):
    try:
        return format(float(x), ",.0f")
    except Exception:
        return ""

def format_pct(x):
    try:
        return format(float(x), ",.2f")
    except Exception:
        return ""

def safe_div(a, b):
    return a / b if b else 0

def parse_province_from_text(s):
    s = "" if pd.isna(s) else str(s).strip()
    if s == "":
        return ""
    for prefix in ["จังหวัด", "จ.", "province "]:
        if s.lower().startswith(prefix.lower()):
            s = s[len(prefix):].strip()
    s = s.split("/")[0].split(",")[0].strip()
    return s

def infer_lazada_province(df):
    candidates = [
        "shippingRegion", "shippingCity", "billingAddr3", "billingCity",
        "shippingAddress", "billingAddr"
    ]
    for c in candidates:
        real = find_col(df, [c])
        if real is not None:
            series = safe_str_series(df[real])
            if series.replace("", pd.NA).notna().sum() > 0:
                return series.apply(parse_province_from_text)
    return pd.Series([""] * len(df), index=df.index)

def detect_header_row(raw_df, required_keywords, scan_rows=8):
    max_rows = min(scan_rows, len(raw_df))
    best_idx = 0
    best_score = -1
    for i in range(max_rows):
        vals = [normalize_col(x) for x in raw_df.iloc[i].tolist()]
        score = 0
        for kw in required_keywords:
            if normalize_col(kw) in vals:
                score += 1
        if score > best_score:
            best_score = score
            best_idx = i
    return best_idx

# ----------------------------
# Column aliases
# ----------------------------
SHOPEE_ALIASES = {
    "order_id": ["หมายเลขคำสั่งซื้อ", "เลขที่คำสั่งซื้อ", "order id", "order_id"],
    "order_datetime": ["วันที่ทำการสั่งซื้อ", "เวลาที่ทำการสั่งซื้อ", "order creation time"],
    "sku": ["sku", "รหัส sku", "เลข sku"],
    "code": ["code", "รหัสลาย", "pattern code"],
    "product_name": ["ชื่อสินค้า", "product name", "ชื่อสินค้าหลัก"],
    "qty": ["จำนวน", "qty", "quantity"],
    "net_sales": ["ราคาขายสุทธิ", "ยอดขายสุทธิ", "net sales", "net sale"],
    "province": ["จังหวัด", "province"],
    "payment_method": ["ช่องทางการชำระเงิน", "payment method", "วิธีชำระเงิน"],
    "licensed_raw": ["licensed", "license", "license name"],
    "item_raw": ["item", "หมวดสินค้า"],
    "type_raw": ["type"],
    "status_raw": ["สถานะการสั่งซื้อ", "status"],
}

LAZADA_ALIASES = {
    "order_id": ["orderitemid", "order item id", "order id", "orderid"],
    "order_datetime": ["createtime", "create time", "created at"],
    "sku": ["sku", "seller sku", "sellersku", "shop sku"],
    "code": ["code", "pattern code"],
    "product_name": ["itemname", "product name", "name"],
    "qty": ["quantity", "qty", "จำนวน"],
    "net_sales": ["paidprice", "paid price", "net sales"],
    "province": ["shippingregion", "shippingcity", "billingaddr3", "billingcity", "shipping address"],
    "payment_method": ["paymethod", "paymentmethod", "payment method"],
    "licensed_raw": ["licensed", "license", "license name"],
    "item_raw": ["item"],
    "type_raw": ["type"],
    "status_raw": ["status", "order status"],
}

CODE_MASTER_ALIASES = {
    "code": ["code"],
    "license_name": ["license name", "licensed", "license"],
    "brand": ["brand"],
    "fabric": ["fabric"],
    "type": ["type"],
    "pattern_display": ["pattern_name_display", "pattern display", "display name", "pattern name"],
}
SKU_MASTER_ALIASES = {
    "sku": ["sku"],
    "brand": ["brand"],
    "item": ["item"],
    "fabric": ["fabric"],
    "type": ["type"],
    "product_name_master": ["product name", "ชื่อสินค้า", "product_name"],
}
URL_PIC_ALIASES = {
    "code": ["code"],
    "image_url": ["url pic", "image url", "url", "pic url"],
}

REQUIRED_STANDARD_COLS = ["order_id", "order_datetime", "sku", "code", "net_sales"]

# ----------------------------
# Business rules
# ----------------------------
def classify_order_status(channel, status_text):
    s = "" if pd.isna(status_text) else str(status_text).strip().lower()

    if s == "":
        return "real_sale"

    if channel.lower() == "shopee":
        cancel_terms = ["ยกเลิก", "cancel"]
        return_terms = ["คืนสินค้า", "คืนเงิน", "return"]
        if any(t in s for t in cancel_terms):
            return "canceled"
        if any(t in s for t in return_terms):
            return "returned"
        return "real_sale"

    # Lazada
    if s in ["canceled", "cancelled"]:
        return "canceled"
    if s in ["returned", "package returned", "return"]:
        return "returned"
    if "cancel" in s:
        return "canceled"
    if "return" in s:
        return "returned"
    return "real_sale"



def get_campaign_day_flags(order_datetime_series):
    dt = pd.to_datetime(order_datetime_series, errors="coerce")
    day = dt.dt.day
    month = dt.dt.month
    is_double_day = (day == month)
    is_midmonth = (day == 15)
    is_payday = (day == 25)

    campaign_day_type = pd.Series(["Normal day"] * len(dt), index=dt.index)
    campaign_day_type.loc[is_double_day.fillna(False)] = "Double day"
    campaign_day_type.loc[is_midmonth.fillna(False)] = "Midmonth"
    campaign_day_type.loc[is_payday.fillna(False)] = "Payday"

    return (
        is_double_day.fillna(False),
        is_midmonth.fillna(False),
        is_payday.fillna(False),
        campaign_day_type
    )

# ----------------------------
# Data preparation
# ----------------------------
def standardize_orders(df, channel, source_name=""):
    alias_map = SHOPEE_ALIASES if channel.lower() == "shopee" else LAZADA_ALIASES
    mapping = auto_map_columns(df, alias_map)

    missing = [k for k in REQUIRED_STANDARD_COLS if mapping.get(k) is None]
    if missing:
        raise ValueError("%s: หา column หลักไม่เจอ -> %s" % (channel, ", ".join(missing)))

    out = pd.DataFrame(index=df.index)
    out["source_file"] = source_name
    out["channel"] = channel
    out["order_id"] = safe_str_series(df[mapping["order_id"]])
    out["order_datetime"] = pd.to_datetime(df[mapping["order_datetime"]], errors="coerce")
    out["sku"] = safe_str_series(df[mapping["sku"]])
    out["code"] = safe_str_series(df[mapping["code"]])
    out["product_name"] = safe_str_series(df[mapping["product_name"]]) if mapping.get("product_name") else ""

    if mapping.get("qty") is not None:
        out["qty"] = pd.to_numeric(df[mapping["qty"]], errors="coerce").fillna(0)
    else:
        out["qty"] = 1

    out["net_sales"] = pd.to_numeric(df[mapping["net_sales"]], errors="coerce").fillna(0)

    if channel.lower() == "lazada":
        out["province"] = infer_lazada_province(df)
    else:
        if mapping.get("province"):
            out["province"] = safe_str_series(df[mapping["province"]]).apply(parse_province_from_text)
        else:
            out["province"] = ""

    if mapping.get("payment_method"):
        out["payment_method"] = safe_str_series(df[mapping["payment_method"]]).replace("", "Unknown")
    else:
        out["payment_method"] = "Unknown"

    out["licensed_raw"] = safe_str_series(df[mapping["licensed_raw"]]) if mapping.get("licensed_raw") else ""
    out["item_raw"] = safe_str_series(df[mapping["item_raw"]]) if mapping.get("item_raw") else ""
    out["type_raw"] = safe_str_series(df[mapping["type_raw"]]) if mapping.get("type_raw") else ""
    out["status_raw"] = safe_str_series(df[mapping["status_raw"]]) if mapping.get("status_raw") else ""
    out["order_class"] = out["status_raw"].apply(lambda x: classify_order_status(channel, x))

    out["order_date"] = out["order_datetime"].dt.date
    out["order_hour"] = out["order_datetime"].dt.hour
    out["year_month"] = out["order_datetime"].dt.to_period("M").astype(str)
    out["weekday"] = out["order_datetime"].dt.day_name()
    out["day_of_month"] = out["order_datetime"].dt.day
    (
        out["is_double_day"],
        out["is_midmonth"],
        out["is_payday"],
        out["campaign_day_type"]
    ) = get_campaign_day_flags(out["order_datetime"])

    return out

def read_master_sheets(master_file):
    xls = pd.ExcelFile(master_file)
    sheet_names = {normalize_col(s): s for s in xls.sheet_names}

    code_sheet = sheet_names.get("code")
    sku_sheet = sheet_names.get("sku")
    url_sheet = None
    for k, v in sheet_names.items():
        if "url" in k and "pic" in k:
            url_sheet = v
            break

    if not code_sheet or not sku_sheet or not url_sheet:
        raise ValueError("SKU-Master ต้องมีแท็บ: Code, SKU, URL Pic")

    sku_raw = pd.read_excel(xls, sheet_name=sku_sheet, header=None)
    sku_header_row = detect_header_row(sku_raw, ["Brand", "SKU", "Product Name", "item"])
    sku_df = pd.read_excel(xls, sheet_name=sku_sheet, header=sku_header_row)

    code_raw = pd.read_excel(xls, sheet_name=code_sheet, header=None)
    code_header_row = detect_header_row(code_raw, ["CODE", "license name", "Brand", "Fabric"])
    code_df = pd.read_excel(xls, sheet_name=code_sheet, header=code_header_row)

    url_raw = pd.read_excel(xls, sheet_name=url_sheet, header=None)
    url_header_row = detect_header_row(url_raw, ["CODE", "URL Pic"])
    url_df = pd.read_excel(xls, sheet_name=url_sheet, header=url_header_row)

    code_map = auto_map_columns(code_df, CODE_MASTER_ALIASES)
    sku_map = auto_map_columns(sku_df, SKU_MASTER_ALIASES)
    url_map = auto_map_columns(url_df, URL_PIC_ALIASES)

    code_std = pd.DataFrame({
        "code": safe_str_series(code_df[code_map["code"]]),
        "license_name": safe_str_series(code_df[code_map["license_name"]]) if code_map.get("license_name") else "",
        "brand_from_code": safe_str_series(code_df[code_map["brand"]]) if code_map.get("brand") else "",
        "fabric_from_code": safe_str_series(code_df[code_map["fabric"]]) if code_map.get("fabric") else "",
        "type_from_code": safe_str_series(code_df[code_map["type"]]) if code_map.get("type") else "",
        "pattern_display": safe_str_series(code_df[code_map["pattern_display"]]) if code_map.get("pattern_display") else "",
    })
    code_std = code_std[code_std["code"] != ""].drop_duplicates(subset=["code"])

    sku_std = pd.DataFrame({
        "sku": safe_str_series(sku_df[sku_map["sku"]]),
        "brand_from_sku": safe_str_series(sku_df[sku_map["brand"]]) if sku_map.get("brand") else "",
        "item": safe_str_series(sku_df[sku_map["item"]]) if sku_map.get("item") else "",
        "fabric_from_sku": safe_str_series(sku_df[sku_map["fabric"]]) if sku_map.get("fabric") else "",
        "type_from_sku": safe_str_series(sku_df[sku_map["type"]]) if sku_map.get("type") else "",
        "product_name_master": safe_str_series(sku_df[sku_map["product_name_master"]]) if sku_map.get("product_name_master") else "",
    })
    sku_std = sku_std[sku_std["sku"] != ""].drop_duplicates(subset=["sku"])

    url_std = pd.DataFrame({
        "code": safe_str_series(url_df[url_map["code"]]),
        "image_url": safe_str_series(url_df[url_map["image_url"]]) if url_map.get("image_url") else "",
    })
    url_std = url_std[url_std["code"] != ""].drop_duplicates(subset=["code"])

    return code_std, sku_std, url_std

def enrich_orders(orders, code_std, sku_std, url_std):
    df = orders.merge(code_std, on="code", how="left")
    df = df.merge(sku_std, on="sku", how="left")
    df = df.merge(url_std, on="code", how="left")

    df["license"] = df["license_name"].replace("", pd.NA).fillna(df["licensed_raw"])
    df["brand"] = df["brand_from_code"].replace("", pd.NA).fillna(df["brand_from_sku"]).fillna("")
    # Fabric from master code tab is source of truth
    df["fabric"] = df["fabric_from_code"].replace("", pd.NA).fillna(df["fabric_from_sku"]).fillna("")
    df["type"] = df["type_from_code"].replace("", pd.NA).fillna(df["type_from_sku"]).fillna(df["type_raw"]).fillna("")
    df["item"] = df["item"].fillna(df["item_raw"]).fillna("")
    df["pattern_display"] = df["pattern_display"].fillna("")
    df["image_status"] = df["image_url"].fillna("").apply(lambda x: "No Image" if str(x).strip() == "" else "Has Image")
    return df

# ----------------------------
# Analytics helpers
# ----------------------------
def make_pattern_table(view):
    if view.empty:
        return pd.DataFrame()

    gp = view.groupby(["code", "license", "brand", "image_url"], dropna=False).agg(
        units=("qty", "sum"),
        net_sales=("net_sales", "sum"),
        orders=("order_id", "nunique"),
    ).reset_index()

    item_gp = view.groupby(["code", "item"], dropna=False)["qty"].sum().reset_index()
    item_gp = item_gp.sort_values(["code", "qty"], ascending=[True, False])

    item_summary_map = {}
    top_item_map = {}
    for code, sub in item_gp.groupby("code"):
        parts = []
        for _, row in sub.head(5).iterrows():
            item_name = str(row["item"]).strip() if str(row["item"]).strip() else "(ไม่ระบุ item)"
            parts.append("%s (%s)" % (item_name, format_int(row["qty"])))
        item_summary_map[code] = " | ".join(parts)
        if len(sub) > 0:
            r0 = sub.iloc[0]
            top_item_name = str(r0["item"]).strip() if str(r0["item"]).strip() else "(ไม่ระบุ item)"
            top_item_map[code] = "%s (%s)" % (top_item_name, format_int(r0["qty"]))
        else:
            top_item_map[code] = ""

    top_channel_map = (
        view.groupby(["code", "channel"])["qty"].sum().reset_index()
        .sort_values(["code", "qty"], ascending=[True, False])
        .drop_duplicates("code")
        .set_index("code")["channel"]
    )

    fabric_map = (
        view.groupby("code")["fabric"]
        .apply(lambda s: ", ".join(sorted([x for x in pd.Series(s).dropna().astype(str).unique().tolist() if x]))[:200])
        .to_dict()
    )
    type_map = (
        view.groupby("code")["type"]
        .apply(lambda s: ", ".join(sorted([x for x in pd.Series(s).dropna().astype(str).unique().tolist() if x]))[:200])
        .to_dict()
    )

    gp["top_channel"] = gp["code"].map(top_channel_map).fillna("")
    gp["top_item"] = gp["code"].map(top_item_map).fillna("")
    gp["item_breakdown"] = gp["code"].map(item_summary_map).fillna("")
    gp["fabric"] = gp["code"].map(fabric_map).fillna("")
    gp["type"] = gp["code"].map(type_map).fillna("")
    gp = gp.sort_values(["units", "net_sales"], ascending=[False, False])
    return gp


def make_cancel_rate_table(all_df):
    if all_df.empty:
        return pd.DataFrame()

    total_gp = all_df.groupby(["code", "license", "brand"], dropna=False).agg(
        total_orders=("order_id", "nunique"),
        total_units=("qty", "sum"),
    ).reset_index()

    cancel_only = all_df[all_df["order_class"].isin(["canceled", "returned"])].copy()

    cancel_orders_map = (
        cancel_only.groupby("code")["order_id"].nunique().to_dict()
        if not cancel_only.empty else {}
    )
    cancel_units_map = (
        cancel_only.groupby("code")["qty"].sum().to_dict()
        if not cancel_only.empty else {}
    )

    total_gp["canceled_orders"] = total_gp["code"].map(cancel_orders_map).fillna(0)
    total_gp["canceled_units"] = total_gp["code"].map(cancel_units_map).fillna(0)
    total_gp["cancel_rate_pct"] = total_gp.apply(
        lambda r: safe_div(r["canceled_orders"], r["total_orders"]) * 100, axis=1
    )

    total_gp = total_gp.sort_values(
        ["canceled_units", "canceled_orders", "cancel_rate_pct", "total_units"],
        ascending=[False, False, False, False]
    )
    return total_gp

def ai_style_summary(df):
    if df.empty:
        return ["ไม่มีข้อมูลตามเงื่อนไขที่เลือก"]
    by_code = df.groupby(["code", "license"], dropna=False)["qty"].sum().sort_values(ascending=False)
    by_channel = df.groupby("channel")["qty"].sum().sort_values(ascending=False)
    by_weekday = df.groupby("weekday")["qty"].sum().sort_values(ascending=False)
    by_province = df.groupby("province")["qty"].sum().sort_values(ascending=False)

    bullets = []
    idx = by_code.index[0]
    bullets.append("ลายเด่นสุด: %s | %s ขาย %s ชิ้น" % (idx[0], idx[1], format_int(by_code.iloc[0])))
    bullets.append("ช่องทางหลัก: %s (%s ชิ้น)" % (by_channel.index[0], format_int(by_channel.iloc[0])))
    bullets.append("วันที่ขายเด่น: %s (%s ชิ้น)" % (by_weekday.index[0], format_int(by_weekday.iloc[0])))
    bullets.append("จังหวัดเด่น: %s (%s ชิ้น)" % (by_province.index[0], format_int(by_province.iloc[0])))
    avg_units_order = df.groupby("order_id")["qty"].sum().mean() if df["order_id"].nunique() else 0
    bullets.append("เฉลี่ย %.2f ชิ้นต่อออเดอร์" % avg_units_order)
    return bullets

# ----------------------------
# UI
# ----------------------------
st.title("Sales Pattern Dashboard V10")
st.caption("รองรับ Shopee + Lazada | ใช้ชื่อคอลัมน์เป็นหลัก | รองรับหลายไฟล์ต่อครั้ง | Fabric map จาก SKU-Master > Code > Fabric | แยกแท็บ Sales / Canceled | แยกวัน Campaign ได้")

with st.sidebar:
    st.header("Upload files")
    shopee_files = st.file_uploader("Shopee Order (Excel)", type=["xlsx", "xls"], accept_multiple_files=True)
    lazada_files = st.file_uploader("Lazada Order (Excel)", type=["xlsx", "xls"], accept_multiple_files=True)
    master_file = st.file_uploader("SKU-Master (Excel)", type=["xlsx", "xls"], accept_multiple_files=False)

    st.markdown("---")
    st.write("- รองรับหลายไฟล์ หลายแบรนด์ หลายเดือน")
    st.write("- Lazada ถ้าไม่มี quantity จะใช้ 1 ต่อแถว")
    st.write("- Master เป็น source of truth")

if not master_file:
    st.info("อัปโหลด SKU-Master ก่อนเริ่มใช้งาน")
    st.stop()

try:
    code_std, sku_std, url_std = read_master_sheets(master_file)
except Exception as e:
    st.error("อ่าน SKU-Master ไม่สำเร็จ: %s" % e)
    st.stop()

frames = []
raw_checks = []
errors = []

for file in shopee_files or []:
    try:
        raw = pd.read_excel(file)
        frames.append(standardize_orders(raw, "Shopee", getattr(file, "name", "Shopee file")))
        raw_checks.append(("Shopee", getattr(file, "name", "Shopee file"), raw.shape[0], raw.shape[1]))
    except Exception as e:
        errors.append("Shopee - %s: %s" % (getattr(file, "name", "file"), e))

for file in lazada_files or []:
    try:
        raw = pd.read_excel(file)
        frames.append(standardize_orders(raw, "Lazada", getattr(file, "name", "Lazada file")))
        raw_checks.append(("Lazada", getattr(file, "name", "Lazada file"), raw.shape[0], raw.shape[1]))
    except Exception as e:
        errors.append("Lazada - %s: %s" % (getattr(file, "name", "file"), e))

for err in errors:
    st.error(err)

if not frames:
    st.warning("กรุณาอัปโหลดไฟล์ Shopee หรือ Lazada อย่างน้อย 1 ไฟล์")
    st.stop()

orders = pd.concat(frames, ignore_index=True)
df = enrich_orders(orders, code_std, sku_std, url_std)


# Tabs
sales_tab, canceled_tab = st.tabs(["Sales", "Canceled"])

# Shared data subsets
sales_df = df[df["order_class"] == "real_sale"].copy()
cancel_df = df[df["order_class"].isin(["canceled", "returned"])].copy()

with sales_tab:
    st.subheader("Analysis Mode")
    m1, m2, m3 = st.columns([1.2, 1.2, 1.8])
    sales_view_mode = m1.radio(
        "ชุดข้อมูลสำหรับ Sales",
        ["Include all sales days", "Exclude double-day", "Exclude double-day + midmonth + payday"],
        horizontal=False
    )
    exclude_double_day = sales_view_mode in ["Exclude double-day", "Exclude double-day + midmonth + payday"]
    exclude_special_days = sales_view_mode == "Exclude double-day + midmonth + payday"

    base_sales_df = sales_df.copy()
    if exclude_double_day:
        base_sales_df = base_sales_df[base_sales_df["is_double_day"] == False]
    if exclude_special_days:
        base_sales_df = base_sales_df[(base_sales_df["is_midmonth"] == False) & (base_sales_df["is_payday"] == False)]

    st.subheader("Filters")
    c1, c2, c3, c4, c5, c6, c7 = st.columns(7)

    month_vals = sorted([x for x in base_sales_df["year_month"].dropna().unique().tolist() if str(x) != "NaT"])
    channel_vals = sorted([x for x in base_sales_df["channel"].dropna().unique().tolist() if x])
    brand_vals = sorted([x for x in base_sales_df["brand"].dropna().unique().tolist() if x])
    license_vals = sorted([x for x in base_sales_df["license"].dropna().unique().tolist() if x])
    fabric_vals = sorted([x for x in base_sales_df["fabric"].dropna().unique().tolist() if x])
    province_vals = sorted([x for x in base_sales_df["province"].dropna().unique().tolist() if x])
    source_vals = sorted([x for x in base_sales_df["source_file"].dropna().unique().tolist() if x])

    sel_month = c1.selectbox("Month", ["All"] + month_vals, key="sales_month")
    sel_channel = c2.selectbox("Channel", ["All"] + channel_vals, key="sales_channel")
    sel_brand = c3.selectbox("Brand", ["All"] + brand_vals, key="sales_brand")
    sel_license = c4.selectbox("License", ["All"] + license_vals, key="sales_license")
    sel_fabric = c5.selectbox("Fabric", ["All"] + fabric_vals, key="sales_fabric")
    sel_province = c6.selectbox("Province", ["All"] + province_vals, key="sales_province")
    sel_source = c7.selectbox("Source File", ["All"] + source_vals, key="sales_source")

    view = base_sales_df.copy()
    if sel_month != "All":
        view = view[view["year_month"] == sel_month]
    if sel_channel != "All":
        view = view[view["channel"] == sel_channel]
    if sel_brand != "All":
        view = view[view["brand"] == sel_brand]
    if sel_license != "All":
        view = view[view["license"] == sel_license]
    if sel_fabric != "All":
        view = view[view["fabric"] == sel_fabric]
    if sel_province != "All":
        view = view[view["province"] == sel_province]
    if sel_source != "All":
        view = view[view["source_file"] == sel_source]

    # KPI
    st.subheader("Executive Overview")
    k1, k2, k3, k4, k5 = st.columns(5)
    units = float(view["qty"].sum())
    sales = float(view["net_sales"].sum())
    orders_n = int(view["order_id"].nunique())
    avg_units = safe_div(units, orders_n)
    avg_sales = safe_div(sales, orders_n)

    k1.metric("Units", format_int(units))
    k2.metric("Net Sales", format_int(sales))
    k3.metric("Orders", format_int(orders_n))
    k4.metric("Avg Units / Order", "%.2f" % avg_units)
    k5.metric("Avg Sales / Order", format_int(avg_sales))

    # Cancellation overview - same filters as sales
    cancel_view = cancel_df.copy()
    if exclude_double_day:
        cancel_view = cancel_view[cancel_view["is_double_day"] == False]
    if exclude_special_days:
        cancel_view = cancel_view[(cancel_view["is_midmonth"] == False) & (cancel_view["is_payday"] == False)]
    if sel_month != "All":
        cancel_view = cancel_view[cancel_view["year_month"] == sel_month]
    if sel_channel != "All":
        cancel_view = cancel_view[cancel_view["channel"] == sel_channel]
    if sel_brand != "All":
        cancel_view = cancel_view[cancel_view["brand"] == sel_brand]
    if sel_license != "All":
        cancel_view = cancel_view[cancel_view["license"] == sel_license]
    if sel_fabric != "All":
        cancel_view = cancel_view[cancel_view["fabric"] == sel_fabric]
    if sel_province != "All":
        cancel_view = cancel_view[cancel_view["province"] == sel_province]
    if sel_source != "All":
        cancel_view = cancel_view[cancel_view["source_file"] == sel_source]

    base_for_rate = df.copy()
    if exclude_double_day:
        base_for_rate = base_for_rate[base_for_rate["is_double_day"] == False]
    if exclude_special_days:
        base_for_rate = base_for_rate[(base_for_rate["is_midmonth"] == False) & (base_for_rate["is_payday"] == False)]
    if sel_month != "All":
        base_for_rate = base_for_rate[base_for_rate["year_month"] == sel_month]
    if sel_channel != "All":
        base_for_rate = base_for_rate[base_for_rate["channel"] == sel_channel]
    if sel_brand != "All":
        base_for_rate = base_for_rate[base_for_rate["brand"] == sel_brand]
    if sel_license != "All":
        base_for_rate = base_for_rate[base_for_rate["license"] == sel_license]
    if sel_fabric != "All":
        base_for_rate = base_for_rate[base_for_rate["fabric"] == sel_fabric]
    if sel_province != "All":
        base_for_rate = base_for_rate[base_for_rate["province"] == sel_province]
    if sel_source != "All":
        base_for_rate = base_for_rate[base_for_rate["source_file"] == sel_source]

    st.subheader("Canceled / Returned Overview")
    x1, x2, x3 = st.columns(3)
    cancel_units = float(cancel_view["qty"].sum()) if len(cancel_view) else 0
    cancel_orders = int(cancel_view["order_id"].nunique()) if len(cancel_view) else 0
    all_orders_filtered = int(base_for_rate["order_id"].nunique()) if len(base_for_rate) else 0
    cancel_rate = safe_div(cancel_orders, all_orders_filtered) * 100
    x1.metric("Canceled/Returned Units", format_int(cancel_units))
    x2.metric("Canceled/Returned Orders", format_int(cancel_orders))
    x3.metric("Canceled Order Rate %", format_pct(cancel_rate))

    with st.expander("Cancel rate by CODE"):
        cancel_rate_df = make_cancel_rate_table(base_for_rate)
        if cancel_rate_df.empty:
            st.info("ไม่พบข้อมูล")
        else:
            show_cancel = cancel_rate_df.head(30).copy()
            show_cancel["total_orders"] = show_cancel["total_orders"].apply(format_int)
            show_cancel["total_units"] = show_cancel["total_units"].apply(format_int)
            show_cancel["canceled_orders"] = show_cancel["canceled_orders"].apply(format_int)
            show_cancel["canceled_units"] = show_cancel["canceled_units"].apply(format_int)
            show_cancel["cancel_rate_pct"] = show_cancel["cancel_rate_pct"].apply(format_pct)
            st.dataframe(show_cancel, use_container_width=True, hide_index=True)

    st.subheader("Campaign Day Mix")
    mix = view.groupby("campaign_day_type")["qty"].sum().sort_values(ascending=False)
    if not mix.empty:
        mix_df = mix.reset_index()
        mix_df.columns = ["Campaign Day Type", "Units"]
        mix_df["Units"] = mix_df["Units"].apply(format_int)
        st.dataframe(mix_df, use_container_width=True, hide_index=True)

    # Summary
    st.subheader("AI-style Summary")
    for bullet in ai_style_summary(view):
        st.markdown("- " + bullet)

    # Main visuals
    left, right = st.columns([1.35, 1])

    with left:
        st.subheader("Top Pattern (CODE + License)")
        top_pattern = make_pattern_table(view)
        if not top_pattern.empty:
            top_pattern["pattern"] = top_pattern["code"].astype(str) + " | " + top_pattern["license"].fillna("").astype(str)
            st.bar_chart(top_pattern.set_index("pattern")["units"].head(10))

            show = top_pattern[["image_url", "code", "license", "brand", "top_item", "item_breakdown", "fabric", "type", "units", "net_sales", "orders", "top_channel"]].head(30).copy()
            show["units"] = show["units"].apply(format_int)
            show["net_sales"] = show["net_sales"].apply(format_int)
            show["orders"] = show["orders"].apply(format_int)
            try:
                st.dataframe(
                    show,
                    use_container_width=True,
                    hide_index=True,
                    column_config={
                        "image_url": st.column_config.ImageColumn("Image", width="medium"),
                        "top_item": st.column_config.TextColumn("top_item", help="item ที่ขายมากที่สุดของ CODE นี้"),
                        "item_breakdown": st.column_config.TextColumn("item_breakdown", help="ยอดรวม item ย่อยของ CODE นี้")
                    }
                )
            except Exception:
                st.dataframe(show, use_container_width=True, hide_index=True)
        else:
            st.info("ไม่มีข้อมูล")

    with right:
        st.subheader("Top License")
        by_license = view.groupby("license", dropna=False)["qty"].sum().sort_values(ascending=False)
        if not by_license.empty:
            st.bar_chart(by_license.head(10))
        else:
            st.info("ไม่มีข้อมูล")

        st.subheader("Channel Split")
        by_channel = view.groupby("channel")["qty"].sum().sort_values(ascending=False)
        if not by_channel.empty:
            st.bar_chart(by_channel)
            ch_df = by_channel.reset_index()
            ch_df.columns = ["Channel", "Units"]
            ch_df["Units"] = ch_df["Units"].apply(format_int)
            st.dataframe(ch_df, use_container_width=True, hide_index=True)
        else:
            st.info("ไม่มีข้อมูล")

    b1, b2 = st.columns(2)
    with b1:
        st.subheader("Buyer Behavior - Weekday")
        weekday_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
        wd = view.groupby("weekday")["qty"].sum().reindex(weekday_order).fillna(0)
        st.bar_chart(wd)

    with b2:
        st.subheader("Buyer Behavior - Hour")
        hr = view.groupby("order_hour")["qty"].sum().sort_index()
        st.bar_chart(hr)

    c1, c2 = st.columns(2)
    with c1:
        st.subheader("Top Province")
        prov = view.groupby("province")["qty"].sum().sort_values(ascending=False).head(15).reset_index()
        if not prov.empty:
            total_units = view["qty"].sum()
            prov["share_pct"] = prov["qty"] / total_units * 100 if total_units else 0
            prov.columns = ["Province", "Units", "% Share"]
            prov["Units"] = prov["Units"].apply(format_int)
            prov["% Share"] = prov["% Share"].apply(format_pct)
            st.dataframe(prov, use_container_width=True, hide_index=True)

    with c2:
        st.subheader("Payment Method")
        pay = view.groupby("payment_method")["qty"].sum().sort_values(ascending=False)
        if not pay.empty:
            st.bar_chart(pay)
        else:
            st.info("ไม่มีข้อมูล")

with canceled_tab:
    st.subheader("Canceled / Returned Detail")
    d1, d2, d3, d4, d5, d6, d7 = st.columns(7)

    month_vals_c = sorted([x for x in cancel_df["year_month"].dropna().unique().tolist() if str(x) != "NaT"])
    channel_vals_c = sorted([x for x in cancel_df["channel"].dropna().unique().tolist() if x])
    brand_vals_c = sorted([x for x in cancel_df["brand"].dropna().unique().tolist() if x])
    license_vals_c = sorted([x for x in cancel_df["license"].dropna().unique().tolist() if x])
    fabric_vals_c = sorted([x for x in cancel_df["fabric"].dropna().unique().tolist() if x])
    province_vals_c = sorted([x for x in cancel_df["province"].dropna().unique().tolist() if x])
    source_vals_c = sorted([x for x in cancel_df["source_file"].dropna().unique().tolist() if x])

    sel_month_c = d1.selectbox("Month", ["All"] + month_vals_c, key="cancel_month")
    sel_channel_c = d2.selectbox("Channel", ["All"] + channel_vals_c, key="cancel_channel")
    sel_brand_c = d3.selectbox("Brand", ["All"] + brand_vals_c, key="cancel_brand")
    sel_license_c = d4.selectbox("License", ["All"] + license_vals_c, key="cancel_license")
    sel_fabric_c = d5.selectbox("Fabric", ["All"] + fabric_vals_c, key="cancel_fabric")
    sel_province_c = d6.selectbox("Province", ["All"] + province_vals_c, key="cancel_province")
    sel_source_c = d7.selectbox("Source File", ["All"] + source_vals_c, key="cancel_source")

    cancel_detail = cancel_df.copy()
    if sel_month_c != "All":
        cancel_detail = cancel_detail[cancel_detail["year_month"] == sel_month_c]
    if sel_channel_c != "All":
        cancel_detail = cancel_detail[cancel_detail["channel"] == sel_channel_c]
    if sel_brand_c != "All":
        cancel_detail = cancel_detail[cancel_detail["brand"] == sel_brand_c]
    if sel_license_c != "All":
        cancel_detail = cancel_detail[cancel_detail["license"] == sel_license_c]
    if sel_fabric_c != "All":
        cancel_detail = cancel_detail[cancel_detail["fabric"] == sel_fabric_c]
    if sel_province_c != "All":
        cancel_detail = cancel_detail[cancel_detail["province"] == sel_province_c]
    if sel_source_c != "All":
        cancel_detail = cancel_detail[cancel_detail["source_file"] == sel_source_c]

    y1, y2, y3 = st.columns(3)
    y1.metric("Canceled/Returned Units", format_int(cancel_detail["qty"].sum()))
    y2.metric("Canceled/Returned Orders", format_int(cancel_detail["order_id"].nunique()))
    y3.metric("Distinct Codes", format_int(cancel_detail["code"].nunique()))

    st.subheader("Top Canceled Codes")
    cancel_code = make_cancel_rate_table(cancel_detail)
    if not cancel_code.empty:
        cancel_code_show = cancel_code.head(50).copy()
        cancel_code_show["total_orders"] = cancel_code_show["total_orders"].apply(format_int)
        cancel_code_show["total_units"] = cancel_code_show["total_units"].apply(format_int)
        cancel_code_show["canceled_orders"] = cancel_code_show["canceled_orders"].apply(format_int)
        cancel_code_show["canceled_units"] = cancel_code_show["canceled_units"].apply(format_int)
        cancel_code_show["cancel_rate_pct"] = cancel_code_show["cancel_rate_pct"].apply(format_pct)
        st.dataframe(cancel_code_show, use_container_width=True, hide_index=True)
    else:
        st.info("ไม่มีข้อมูล")

    st.subheader("Canceled Raw Detail")
    raw_cols = ["source_file", "channel", "order_id", "order_datetime", "code", "license", "brand", "item", "fabric", "qty", "net_sales", "province", "payment_method", "status_raw", "order_class"]
    raw_show = cancel_detail[raw_cols].copy()
    raw_show["qty"] = raw_show["qty"].apply(format_int)
    raw_show["net_sales"] = raw_show["net_sales"].apply(format_int)
    st.dataframe(raw_show.head(200), use_container_width=True, hide_index=True)

with st.expander("Data quality check"):
    st.write("Raw files loaded:", raw_checks)
    st.write("Rows after standardization:", len(orders))
    st.write("Rows after enrichment:", len(df))
    st.write("Real sale rows:", len(sales_df))
    st.write("Canceled/returned rows:", len(cancel_df))
    st.write("Campaign day types:", sorted(df["campaign_day_type"].dropna().unique().tolist()))
    st.dataframe(df.head(20), use_container_width=True)
# KPI
st.subheader("Executive Overview")
k1, k2, k3, k4, k5 = st.columns(5)
units = float(view["qty"].sum())
sales = float(view["net_sales"].sum())
orders_n = int(view["order_id"].nunique())
avg_units = safe_div(units, orders_n)
avg_sales = safe_div(sales, orders_n)

k1.metric("Units", format_int(units))
k2.metric("Net Sales", format_int(sales))
k3.metric("Orders", format_int(orders_n))
k4.metric("Avg Units / Order", "%.2f" % avg_units)
k5.metric("Avg Sales / Order", format_int(avg_sales))

# Cancellation overview - ใช้ filter เดียวกันกับหน้าหลัก ยกเว้น view mode
cancel_view = cancel_df.copy()
if sel_month != "All":
    cancel_view = cancel_view[cancel_view["year_month"] == sel_month]
if sel_channel != "All":
    cancel_view = cancel_view[cancel_view["channel"] == sel_channel]
if sel_brand != "All":
    cancel_view = cancel_view[cancel_view["brand"] == sel_brand]
if sel_license != "All":
    cancel_view = cancel_view[cancel_view["license"] == sel_license]
if sel_fabric != "All":
    cancel_view = cancel_view[cancel_view["fabric"] == sel_fabric]
if sel_province != "All":
    cancel_view = cancel_view[cancel_view["province"] == sel_province]
if sel_source != "All":
    cancel_view = cancel_view[cancel_view["source_file"] == sel_source]

base_for_rate = df.copy()
if sel_month != "All":
    base_for_rate = base_for_rate[base_for_rate["year_month"] == sel_month]
if sel_channel != "All":
    base_for_rate = base_for_rate[base_for_rate["channel"] == sel_channel]
if sel_brand != "All":
    base_for_rate = base_for_rate[base_for_rate["brand"] == sel_brand]
if sel_license != "All":
    base_for_rate = base_for_rate[base_for_rate["license"] == sel_license]
if sel_fabric != "All":
    base_for_rate = base_for_rate[base_for_rate["fabric"] == sel_fabric]
if sel_province != "All":
    base_for_rate = base_for_rate[base_for_rate["province"] == sel_province]
if sel_source != "All":
    base_for_rate = base_for_rate[base_for_rate["source_file"] == sel_source]

st.subheader("Canceled / Returned Overview")
x1, x2, x3 = st.columns(3)
cancel_units = float(cancel_view["qty"].sum()) if len(cancel_view) else 0
cancel_orders = int(cancel_view["order_id"].nunique()) if len(cancel_view) else 0
all_orders_filtered = int(base_for_rate["order_id"].nunique()) if len(base_for_rate) else 0
cancel_rate = safe_div(cancel_orders, all_orders_filtered) * 100
x1.metric("Canceled/Returned Units", format_int(cancel_units))
x2.metric("Canceled/Returned Orders", format_int(cancel_orders))
x3.metric("Canceled Order Rate %", format_pct(cancel_rate))

with st.expander("Cancel rate by CODE"):
    cancel_rate_df = make_cancel_rate_table(base_for_rate)
    if cancel_rate_df.empty:
        st.info("ไม่พบข้อมูล")
    else:
        show_cancel = cancel_rate_df.head(30).copy()
        show_cancel["total_orders"] = show_cancel["total_orders"].apply(format_int)
        show_cancel["total_units"] = show_cancel["total_units"].apply(format_int)
        show_cancel["canceled_orders"] = show_cancel["canceled_orders"].apply(format_int)
        show_cancel["canceled_units"] = show_cancel["canceled_units"].apply(format_int)
        show_cancel["cancel_rate_pct"] = show_cancel["cancel_rate_pct"].apply(format_pct)
        st.dataframe(show_cancel, use_container_width=True, hide_index=True)

# Summary
st.subheader("AI-style Summary")
for bullet in ai_style_summary(view):
    st.markdown("- " + bullet)

# Main visuals
left, right = st.columns([1.35, 1])

with left:
    st.subheader("Top Pattern (CODE + License)")
    top_pattern = make_pattern_table(view)
    if not top_pattern.empty:
        top_pattern["pattern"] = top_pattern["code"].astype(str) + " | " + top_pattern["license"].fillna("").astype(str)
        st.bar_chart(top_pattern.set_index("pattern")["units"].head(10))

        show = top_pattern[["image_url", "code", "license", "brand", "top_item", "item_breakdown", "fabric", "type", "units", "net_sales", "orders", "top_channel"]].head(30).copy()
        show["units"] = show["units"].apply(format_int)
        show["net_sales"] = show["net_sales"].apply(format_int)
        show["orders"] = show["orders"].apply(format_int)
        try:
            st.dataframe(
                show,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "image_url": st.column_config.ImageColumn("Image", width="medium"),
                    "top_item": st.column_config.TextColumn("top_item", help="item ที่ขายมากที่สุดของ CODE นี้"),
                    "item_breakdown": st.column_config.TextColumn("item_breakdown", help="ยอดรวม item ย่อยของ CODE นี้")
                }
            )
        except Exception:
            st.dataframe(show, use_container_width=True, hide_index=True)
    else:
        st.info("ไม่มีข้อมูล")

with right:
    st.subheader("Top License")
    by_license = view.groupby("license", dropna=False)["qty"].sum().sort_values(ascending=False)
    if not by_license.empty:
        st.bar_chart(by_license.head(10))
    else:
        st.info("ไม่มีข้อมูล")

    st.subheader("Channel Split")
    by_channel = view.groupby("channel")["qty"].sum().sort_values(ascending=False)
    if not by_channel.empty:
        st.bar_chart(by_channel)
        ch_df = by_channel.reset_index()
        ch_df.columns = ["Channel", "Units"]
        ch_df["Units"] = ch_df["Units"].apply(format_int)
        st.dataframe(ch_df, use_container_width=True, hide_index=True)
    else:
        st.info("ไม่มีข้อมูล")

b1, b2 = st.columns(2)
with b1:
    st.subheader("Buyer Behavior - Weekday")
    weekday_order = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    wd = view.groupby("weekday")["qty"].sum().reindex(weekday_order).fillna(0)
    st.bar_chart(wd)

with b2:
    st.subheader("Buyer Behavior - Hour")
    hr = view.groupby("order_hour")["qty"].sum().sort_index()
    st.bar_chart(hr)

c1, c2 = st.columns(2)
with c1:
    st.subheader("Top Province")
    prov = view.groupby("province")["qty"].sum().sort_values(ascending=False).head(15).reset_index()
    if not prov.empty:
        total_units = view["qty"].sum()
        prov["share_pct"] = prov["qty"] / total_units * 100 if total_units else 0
        prov.columns = ["Province", "Units", "% Share"]
        prov["Units"] = prov["Units"].apply(format_int)
        prov["% Share"] = prov["% Share"].apply(format_pct)
        st.dataframe(prov, use_container_width=True, hide_index=True)

with c2:
    st.subheader("Payment Method")
    pay = view.groupby("payment_method")["qty"].sum().sort_values(ascending=False)
    if not pay.empty:
        st.bar_chart(pay)
    else:
        st.info("ไม่มีข้อมูล")


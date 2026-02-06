import streamlit as st
import pandas as pd
import re
import io
import zipfile
from datetime import datetime

# ==========================================
# 0. PAGE CONFIG & KIOSK MODE (EXTREME CLEAN UI)
# ==========================================

# This must be the very first Streamlit command
st.set_page_config(page_title="Payroll Processor", layout="wide")

# CSS to hide the top header, hamburger menu, footer, "Manage app" button,
# and specifically the profile container and Streamlit host badge.
hide_st_style = """
            <style>
            header {visibility: hidden !important;}
            #MainMenu {visibility: hidden !important;}
            footer {visibility: hidden !important;}
            .stDeployButton {display:none !important;}
            .stAppDeployButton {display:none !important;}
            
            [class*="_profileContainer_"], [class*="_profilePreview_"] {
                display: none !important;
            }
            [class*="_viewerBadge_"], [class*="_container_gzau3_"] {
                display: none !important;
            }
            .stActionButton, .stStatusWidget, [data-testid="stStatusWidget"], [data-testid="appCreatorAvatar"] {
                display: none !important;
            }
            .block-container {
                padding-top: 1rem !important;
            }
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

# ==========================================
# 1. SHARED UTILITY FUNCTIONS
# ==========================================

def parse_duration_to_decimal(duration_str):
    """Convert duration string (H:MM or HH:MM or decimal) to decimal hours."""
    try:
        duration_str_clean = str(duration_str).strip()
        if ':' not in duration_str_clean:
            return round(float(duration_str_clean), 2)
        parts = duration_str_clean.split(':')
        hours = int(parts[0])
        minutes = int(parts[1])
        decimal_hours = hours + (minutes / 60)
        return round(decimal_hours, 2)
    except:
        return pd.NA

def get_week_number(day_str, pay_period_start):
    """Determine which week (1 or 2) a day belongs to."""
    try:
        if isinstance(day_str, str):
            date_obj = datetime.strptime(day_str, "%m/%d/%Y")
        else:
            date_obj = day_str
        
        if isinstance(pay_period_start, datetime):
            start_date = pay_period_start
        else:
            start_date = datetime.combine(pay_period_start, datetime.min.time())

        days_diff = (date_obj - start_date).days
        
        if 0 <= days_diff <= 6:
            return date_obj, 1
        elif 7 <= days_diff <= 13:
            return date_obj, 2
        else:
            return date_obj, None
    except Exception as e:
        return None, None

def detect_file_format(file_content_str):
    try:
        head = file_content_str[:1000]
        if 'Previous Payroll Report' in head or 'Reclose Payroll Report' in head:
            return 'payroll'
        elif 'Timeclock Report' in head or 'All Employees:' in head or 'Timeclock Summary' in head:
            return 'timeclock'
        if 'Clockset' in head and 'ACTIVE' in head:
            return 'timeclock'
        return 'payroll'
    except Exception as e:
        return None

# ==========================================
# 2. PARSING LOGIC: PAYROLL STRUCTURE
# ==========================================

def parse_payroll_structure(content):
    data = []
    store_no = None
    file_lines = io.StringIO(content)
    
    header_year_match = re.search(r'Period: (\d{2})/(\d{2})/(\d{4})', content)
    if header_year_match:
        header_start_month = int(header_year_match.group(1))
        header_start_year = int(header_year_match.group(3))
    else:
        header_start_month = 12
        header_start_year = datetime.now().year

    for line in file_lines:
        line = line.strip()
        if not line: continue
        if any(x in line for x in ["Popeye's", "Popeyes", "POPEYES"]):
            match = re.search(r"(?:Popeye's|Popeyes|POPEYES)\s*#?\s*(\d+)", line, re.IGNORECASE)
            if not match: match = re.search(r'#(\d+)', line)
            if match: store_no = match.group(1)
            continue
        
        parts = None
        if '","' in line:
            parts = [p.strip().strip('"') for p in line.split('","')]
            if parts:
                parts[0] = parts[0].lstrip('"')
                parts[-1] = parts[-1].rstrip('"\n')
        elif ',' in line and not line.startswith('"'):
            parts = [p.strip() for p in line.split(',')]

        if parts is None:
            ot_match = re.match(r'^\s*"?(\d+)\s+([\d\.]+)\s*"?$', line)
            if ot_match:
                try:
                    data.append({
                        'emp_id': ot_match.group(1).strip(),
                        'first_name': 'OVERTIME', 'last_name': 'REPORTED',
                        'day': '', 'date': '', 'start_time': '', 'end_time': '',
                        'type': 'Overtime_Reported', 
                        'duration': ot_match.group(2).strip(),
                        'decimal_hours': round(float(ot_match.group(2).strip()), 2),
                        'store_no': store_no
                    })
                except: continue
            continue 

        day_of_week = parts[0].strip()
        if day_of_week in ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']:
            if len(parts) < 11: continue
            date_str, duration_decimal, duration_hhmm = parts[1].strip(), parts[3].strip(), parts[2].strip()
            emp_id, first_name, last_name = parts[6].strip(), parts[8].strip(), parts[9].strip()
            emp_id_match = re.search(r'^(\d+)', emp_id)
            emp_id = emp_id_match.group(1) if emp_id_match else ''
            first_name = re.sub(r'--.*', '', first_name).strip()
            last_name = re.sub(r'--.*', '', last_name).strip()
            
            if duration_decimal in ['--', ''] or not emp_id: continue
            
            full_date = date_str
            try:
                if '-' in date_str:
                    month_match = re.search(r'(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)', date_str)
                    if month_match:
                        month_abbr = month_match.group(1)
                        month_num = datetime.strptime(month_abbr, "%b").month
                        if header_start_month == 12 and month_num <= 6:
                            correct_year = header_start_year + 1
                        elif header_start_month <= 6 and month_num == 12:
                            correct_year = header_start_year - 1
                        else:
                            correct_year = header_start_year
                        date_obj = datetime.strptime(f"{date_str}-{correct_year}", "%d-%b-%Y")
                        full_date = date_obj.strftime("%m/%d/%Y")
            except: pass
            
            try:
                data.append({
                    'emp_id': emp_id, 'first_name': first_name, 'last_name': last_name,
                    'day': day_of_week, 'date': full_date, 'start_time': '', 'end_time': '',
                    'type': 'Clockset', 'duration': duration_hhmm,
                    'decimal_hours': round(float(duration_decimal), 2), 'store_no': store_no
                })
            except: continue

    df = pd.DataFrame(data)
    if not df.empty and 'type' in df.columns:
        name_map = df[df['type'] == 'Clockset'].groupby('emp_id').agg(
            first_name=('first_name', 'first'), last_name=('last_name', 'first')
        ).reset_index()
        for index, row in df[df['type'] == 'Overtime_Reported'].iterrows():
            match = name_map[name_map['emp_id'].str.startswith(str(row['emp_id']), na=False)]
            if not match.empty:
                df.loc[index, 'first_name'], df.loc[index, 'last_name'] = match.iloc[0]['first_name'], match.iloc[0]['last_name']
            else: df.drop(index, inplace=True)
    return df, store_no

# ==========================================
# 3. PARSING LOGIC: TIMECLOCK STRUCTURE
# ==========================================

def parse_timeclock_structure(content):
    data, current_emp_id, current_first_name, current_last_name, store_no = [], None, None, None, None
    lines = content.splitlines()
    for line in lines:
        line = line.strip()
        if not line: continue
        parts = [p.strip().strip('"') for p in (line.split('","') if '","' in line else line.split(','))]
        if any(x in parts[0] for x in ["Popeye's", 'POPEYES', "Popeyes", "POPEYE'S"]):
            match = re.search(r"(?:Popeye's|POPEYES|Popeyes)\s*#?\s*(\d+)", parts[0], re.IGNORECASE)
            if not match: match = re.search(r'#(\d+)', parts[0])
            if match: store_no = match.group(1)
            continue
        if parts[0].strip().isdigit() and len(parts) >= 3:
            current_emp_id, current_first_name, current_last_name = parts[0].strip(), parts[1].strip(), parts[2].strip()
            continue
        if len(parts) >= 6 and current_emp_id:
            day_idx = 2
            if parts[1] in ['*O', '*I', '**']: day_idx = 2
            if len(parts) > day_idx + 4:
                day, d_raw, e_raw, e_type, dur = parts[day_idx], parts[day_idx+1], parts[day_idx+2], parts[day_idx+3], parts[day_idx+4]
                if e_type.strip() in ['Clockset', 'Clockset  ', 'Paid Break']:
                    d_m, t1, t2 = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', d_raw), re.search(r'(\d{1,2}:\d{2})', d_raw), re.search(r'(\d{1,2}:\d{2})', e_raw)
                    data.append({
                        'emp_id': current_emp_id, 'first_name': current_first_name, 'last_name': current_last_name,
                        'day': day, 'date': d_m.group(1) if d_m else '', 'start_time': t1.group(1) if t1 else '',
                        'end_time': t2.group(1) if t2 else '', 'type': e_type.strip(), 'duration': dur,
                        'decimal_hours': parse_duration_to_decimal(dur), 'store_no': store_no
                    })
    return pd.DataFrame(data), store_no

# ==========================================
# 4. DATA GENERATION FUNCTIONS
# ==========================================

def generate_formatted_data(df, store_no):
    if df.empty: return pd.DataFrame()
    daily_df = df[df['type'].isin(['Clockset', 'Paid Break'])].copy()
    return pd.DataFrame({
        'store_no': store_no if store_no else daily_df.get('store_no', ''),
        'emp_id': daily_df['emp_id'],
        'first_name': daily_df['first_name'],
        'last_name': daily_df['last_name'],
        'day': daily_df['day'],
        'date': daily_df['date'],
        'start_time': daily_df['start_time'],
        'end_time': daily_df['end_time'],
        'type': daily_df['type'],
        'duration': daily_df['decimal_hours']
    })

def generate_pivot_data(df, store_no, pay_period_start):
    if df.empty: return pd.DataFrame()
    daily_clock_df = df[df['type'].isin(['Clockset', 'Paid Break'])].copy()
    if daily_clock_df.empty: return pd.DataFrame()
    daily_clock_df[['date_obj', 'week']] = daily_clock_df['date'].apply(lambda x: pd.Series(get_week_number(x, pay_period_start)))
    daily_clock_df = daily_clock_df[daily_clock_df['week'].notna()].copy()
    ws = daily_clock_df.groupby(['emp_id', 'first_name', 'last_name', 'week']).agg(wh=('decimal_hours', 'sum')).reset_index()
    ws['calc_reg'], ws['calc_ot'] = ws['wh'].apply(lambda x: min(x, 40)), ws['wh'].apply(lambda x: max(0, x - 40))
    p = ws.groupby(['emp_id', 'first_name', 'last_name']).agg(total=('wh', 'sum'), regular=('calc_reg', 'sum'), overtime=('calc_ot', 'sum')).reset_index()
    reported_ot_df = df[df['type'] == 'Overtime_Reported'].copy()
    if not reported_ot_df.empty:
        rots = reported_ot_df.groupby('emp_id').agg(reported_overtime=('decimal_hours', 'sum')).reset_index()
        p = pd.merge(p, rots, on='emp_id', how='left')
        p['overtime'] = p['reported_overtime'].fillna(p['overtime'])
        p['regular'] = p['total'] - p['overtime']
        p.drop(columns=['reported_overtime'], inplace=True)
    p['store_no'], p['name'] = store_no, ''
    p = p[['store_no', 'name', 'total', 'regular', 'overtime', 'emp_id', 'first_name', 'last_name']]
    p.columns = ['store no', 'name', 'total', 'regular', 'overtime', 'id', 'first name', 'last name']
    return p.round(2)

def generate_wage_split_data(df, store_no, pay_period_start, wage_change_date):
    if df.empty: return pd.DataFrame()
    daily_clock_df = df[df['type'].isin(['Clockset', 'Paid Break'])].copy()
    if daily_clock_df.empty: return pd.DataFrame()
    daily_clock_df[['date_obj', 'week']] = daily_clock_df['date'].apply(lambda x: pd.Series(get_week_number(x, pay_period_start)))
    daily_clock_df = daily_clock_df[daily_clock_df['week'].notna()].copy()
    wc_date = datetime.combine(wage_change_date, datetime.min.time())
    daily_clock_df['wage_period'] = daily_clock_df['date_obj'].apply(lambda x: '2025' if x < wc_date else '2026')
    wt = daily_clock_df.groupby(['emp_id', 'first_name', 'last_name', 'week']).agg(twh=('decimal_hours', 'sum')).reset_index()
    wt['wrh'], wt['woh'] = wt['twh'].apply(lambda x: min(x, 40)), wt['twh'].apply(lambda x: max(0, x - 40))
    daily_clock_df = pd.merge(daily_clock_df, wt[['emp_id', 'week', 'twh', 'wrh', 'woh']], on=['emp_id', 'week'], how='left')
    daily_clock_df['dp'] = daily_clock_df.apply(lambda r: r['decimal_hours'] / r['twh'] if r['twh'] > 0 else 0, axis=1)
    daily_clock_df['drh'], daily_clock_df['doh'] = daily_clock_df['dp'] * daily_clock_df['wrh'], daily_clock_df['dp'] * daily_clock_df['woh']
    summary = daily_clock_df.groupby(['emp_id', 'first_name', 'last_name', 'wage_period']).agg(th=('decimal_hours', 'sum'), rh=('drh', 'sum'), oh=('doh', 'sum')).reset_index()
    p25 = summary[summary['wage_period'] == '2025'][['emp_id', 'first_name', 'last_name', 'th', 'rh', 'oh']].rename(columns={'th':'total_hours_2025', 'rh':'regular_2025', 'oh':'overtime_2025'})
    p26 = summary[summary['wage_period'] == '2026'][['emp_id', 'first_name', 'last_name', 'th', 'rh', 'oh']].rename(columns={'th':'total_hours_2026', 'rh':'regular_2026', 'oh':'overtime_2026'})
    wide = pd.merge(p25, p26, on=['emp_id', 'first_name', 'last_name'], how='outer').fillna(0)
    wide.insert(0, 'store_no', store_no)
    wide.insert(1, 'name', '')
    wide.rename(columns={'emp_id': 'id', 'first_name': 'first name', 'last_name': 'last name'}, inplace=True)
    return wide.round(2)

# ==========================================
# 5. STREAMLIT APP INTERFACE
# ==========================================

st.title("📊 Payroll & Timeclock Processor")
st.markdown("Upload multiple store CSV files, set your dates, and download a consolidated report in one click.")

st.markdown("### ⚙️ Step 1: Configuration")
expander = st.expander("Click to set Pay Period and Wage Dates", expanded=True)
with expander:
    col_a, col_b = st.columns(2)
    with col_a:
        today = datetime.now()
        pay_period_start = st.date_input("Pay Period Start Date", value=today)
    with col_b:
        wage_change_active = st.checkbox("Apply Wage Split?", value=True)
        wage_change_date = st.date_input("Wage Change Date", value=datetime(2026, 1, 1)) if wage_change_active else None
    
    # NEW FEATURE: Separate Output Checkbox
    separate_output = st.checkbox("Generate Separate Output for each File?", value=False)

st.markdown("### 📁 Step 2: Upload Files")
uploaded_files = st.file_uploader("Drop your CSV Files here (Select Multiple)", accept_multiple_files=True, type=['csv'])

if st.button("🚀 Start Processing", type="primary"):
    if not uploaded_files:
        st.error("Please upload at least one CSV file.")
    else:
        # Dictionary to store results
        # If combined: { "all": DataFrame }
        # If separate: { "filename": DataFrame }
        processed_data_map = {}
        progress_bar = st.progress(0)
        status_text = st.empty()
        pp_start_dt = datetime.combine(pay_period_start, datetime.min.time())

        for i, uploaded_file in enumerate(uploaded_files):
            status_text.text(f"Processing {uploaded_file.name}...")
            
            try:
                content = uploaded_file.getvalue().decode("utf-8")
            except UnicodeDecodeError:
                content = uploaded_file.getvalue().decode("latin-1")

            file_format = detect_file_format(content)
            df, store_no = (parse_payroll_structure(content) if file_format == 'payroll' else parse_timeclock_structure(content))
            
            if not df.empty and store_no:
                if separate_output:
                    # Keep per filename
                    # Remove .csv from name for folder naming
                    clean_name = re.sub(r'\.csv$', '', uploaded_file.name, flags=re.IGNORECASE)
                    processed_data_map[clean_name] = {store_no: df}
                else:
                    # Standard Combined Logic
                    if "combined" not in processed_data_map:
                        processed_data_map["combined"] = {}
                    if store_no in processed_data_map["combined"]:
                        processed_data_map["combined"][store_no] = pd.concat([processed_data_map["combined"][store_no], df], ignore_index=True)
                    else:
                        processed_data_map["combined"][store_no] = df
            
            progress_bar.progress((i + 1) / len(uploaded_files))

        if not processed_data_map:
            st.warning("No valid data was extracted. Please check your files.")
        else:
            status_text.text("Generating ZIP file...")
            zip_buffer = io.BytesIO()
            
            with zipfile.ZipFile(zip_buffer, "w") as zf:
                for group_name, store_dict in processed_data_map.items():
                    all_fmt, all_pvt, all_wge = [], [], []
                    
                    for s_no, df in sorted(store_dict.items()):
                        all_fmt.append(generate_formatted_data(df, s_no))
                        all_pvt.append(generate_pivot_data(df, s_no, pp_start_dt))
                        if wage_change_active and wage_change_date:
                            all_wge.append(generate_wage_split_data(df, s_no, pp_start_dt, wage_change_date))

                    # Path prefix inside zip
                    prefix = "" if group_name == "combined" else f"{group_name}/"

                    if all_fmt:
                        zf.writestr(f"{prefix}All_Stores_Formatted.csv", pd.concat(all_fmt).to_csv(index=False).encode('utf-8'))
                    if all_pvt:
                        zf.writestr(f"{prefix}All_Stores_Pivot.csv", pd.concat(all_pvt).to_csv(index=False).encode('utf-8'))
                    if all_wge:
                        zf.writestr(f"{prefix}All_Stores_WageSplit.csv", pd.concat(all_wge).to_csv(index=False).encode('utf-8'))

            st.success("Processing Complete!")
            st.download_button(
                label="📥 Download Results (ZIP)",
                data=zip_buffer.getvalue(),
                file_name="payroll_results.zip",
                mime="application/zip",
                use_container_width=True
            )

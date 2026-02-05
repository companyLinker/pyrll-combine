import streamlit as st
import pandas as pd
import re
import io
import zipfile
from datetime import datetime

# ==========================================
# 0. PAGE CONFIG & KIOSK MODE (HIDES GITHUB LINKS)
# ==========================================

# This must be the very first Streamlit command
st.set_page_config(page_title="Payroll Processor", layout="wide")

# CSS to hide the top header, hamburger menu, and footer
hide_st_style = """
            <style>
            #MainMenu {visibility: hidden;}
            footer {visibility: hidden;}
            header {visibility: hidden;}
            .stDeployButton {display:none;}
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
        # Convert date/datetime object to standardized datetime
        if isinstance(day_str, str):
            date_obj = datetime.strptime(day_str, "%m/%d/%Y")
        else:
            date_obj = day_str
        
        # Ensure pay_period_start is datetime
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
    """
    Reads the content string to detect if the file is 
    'payroll' (Previous Payroll) or 'timeclock' (Timeclock Sheet).
    """
    try:
        # Check first 1000 characters for keywords
        head = file_content_str[:1000]
        
        if 'Previous Payroll Report' in head or 'Reclose Payroll Report' in head:
            return 'payroll'
        elif 'Timeclock Report' in head or 'All Employees:' in head or 'Timeclock Summary' in head:
            return 'timeclock'
        
        if 'Clockset' in head and 'ACTIVE' in head:
            return 'timeclock'
            
        return 'payroll' # Default fallback
    except Exception as e:
        return None

# ==========================================
# 2. PARSING LOGIC: PAYROLL STRUCTURE
# ==========================================

def parse_payroll_structure(content):
    """Parses the 'Previous Payroll' content string."""
    data = []
    store_no = None
    
    file_lines = io.StringIO(content)
    
    # Extract year/date from full content for header logic
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
        
        # Extract store number
        if "Popeye's" in line or "Popeyes" in line or "POPEYES" in line:
            match = re.search(r"(?:Popeye's|Popeyes|POPEYES)\s*#?\s*(\d+)", line, re.IGNORECASE)
            if not match: 
                match = re.search(r'#(\d+)', line)
            if match: 
                store_no = match.group(1)
            continue
        
        # Dynamic Line Splitting
        parts = None
        if '","' in line:
            parts = [p.strip().strip('"') for p in line.split('","')]
            if parts:
                parts[0] = parts[0].lstrip('"')
                parts[-1] = parts[-1].rstrip('"\n')
        elif ',' in line and not line.startswith('"'):
            parts = [p.strip() for p in line.split(',')]

        if parts is None:
            # Check for Overtime Line
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
            continue 

        day_of_week = parts[0].strip()
        if day_of_week in ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']:
            if len(parts) < 11: continue
            
            date_str = parts[1].strip()
            duration_decimal = parts[3].strip() 
            duration_hhmm = parts[2].strip()
            emp_id = parts[6].strip()
            first_name = parts[8].strip() 
            last_name = parts[9].strip()
            
            # Clean ID
            emp_id_match = re.search(r'^(\d+)', emp_id)
            emp_id = emp_id_match.group(1) if emp_id_match else ''
            
            # Clean Names
            first_name = re.sub(r'--.*', '', first_name).strip()
            last_name = re.sub(r'--.*', '', last_name).strip()
            
            if duration_decimal in ['--', ''] or not emp_id: continue
            
            # Date Formatting logic (reused from original)
            full_date = date_str
            try:
                if '-' in date_str:
                    if any(m in date_str for m in ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']):
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
                    
                    elif len(date_str.split('-')[0]) <= 2:
                        parts_date = date_str.split('-')
                        if len(parts_date) == 2:
                            month_num = int(parts_date[0]) if len(parts_date[0]) <= 2 else int(parts_date[1])
                            
                            if header_start_month == 12 and month_num <= 6:
                                correct_year = header_start_year + 1
                            elif header_start_month <= 6 and month_num == 12:
                                correct_year = header_start_year - 1
                            else:
                                correct_year = header_start_year
                            
                            date_obj = datetime.strptime(f"{date_str}-{correct_year}", "%m-%d-%Y")
                            full_date = date_obj.strftime("%m/%d/%Y")
            except Exception:
                pass
            
            try:
                decimal_hours = float(duration_decimal)
                data.append({
                    'emp_id': emp_id,
                    'first_name': first_name,
                    'last_name': last_name,
                    'day': day_of_week,
                    'date': full_date,
                    'start_time': '',
                    'end_time': '',
                    'type': 'Clockset',
                    'duration': duration_hhmm,
                    'decimal_hours': round(decimal_hours, 2),
                    'store_no': store_no
                })
            except ValueError: continue

    df = pd.DataFrame(data)
    
    # Map names to Overtime entries
    if not df.empty and 'type' in df.columns:
        name_map = df[df['type'] == 'Clockset'].groupby('emp_id').agg(
            first_name=('first_name', 'first'),
            last_name=('last_name', 'first')
        ).reset_index()

        for index, row in df[df['type'] == 'Overtime_Reported'].iterrows():
            match = name_map[name_map['emp_id'].str.startswith(str(row['emp_id']), na=False)]
            if not match.empty:
                df.loc[index, 'first_name'] = match.iloc[0]['first_name']
                df.loc[index, 'last_name'] = match.iloc[0]['last_name']
            else:
                df.drop(index, inplace=True)

    return df, store_no

# ==========================================
# 3. PARSING LOGIC: TIMECLOCK STRUCTURE
# ==========================================

def parse_timeclock_structure(content):
    """Parses the 'Timeclock Report' content string."""
    data = []
    current_emp_id = None
    current_first_name = None
    current_last_name = None
    store_no = None
    
    # Split content into lines
    lines = content.splitlines()
        
    for line in lines:
        line = line.strip()
        if not line: continue
            
        if '","' in line:
            parts = [p.strip().strip('"') for p in line.split('","')]
        else:
            parts = [p.strip() for p in line.split(',')]
        
        # Store Number
        if "Popeye's" in parts[0] or 'POPEYES' in parts[0] or "Popeyes" in parts[0] or "POPEYE'S" in parts[0]:
            match = re.search(r"(?:Popeye's|POPEYES|Popeyes)\s*#?\s*(\d+)", parts[0], re.IGNORECASE)
            if not match: 
                match = re.search(r'#(\d+)', parts[0])
            if match: 
                store_no = match.group(1)
            continue
        # Skip Headers/Footers
        if any(k in parts[0] for k in ['Timeclock Summary', 'Total Paid', 'Active Employees', 'Timeclock Report', 'VIOLATION']):
            continue
        
        # Employee Header (ID is digits, 3rd col exists)
        if parts[0].strip().isdigit() and len(parts) >= 3:
            current_emp_id = parts[0].strip()
            current_first_name = parts[1].strip()
            current_last_name = parts[2].strip()
            continue
        
        # Data Line
        if len(parts) >= 6 and current_emp_id:
            day_idx = 2
            if parts[1] in ['*O', '*I', '**']: day_idx = 2
            
            if len(parts) > day_idx + 4:
                day_of_week = parts[day_idx].strip()
                date_str_raw = parts[day_idx+1].strip()
                end_time_raw = parts[day_idx+2].strip()
                entry_type = parts[day_idx+3].strip()
                duration = parts[day_idx+4].strip()
                
                if entry_type in ['Clockset', 'Clockset  ', 'Paid Break']:
                    # Parse Date
                    date_match = re.search(r'(\d{1,2}/\d{1,2}/\d{4})', date_str_raw)
                    clean_date = date_match.group(1) if date_match else ''
                    
                    t1 = re.search(r'(\d{1,2}:\d{2})', date_str_raw)
                    t2 = re.search(r'(\d{1,2}:\d{2})', end_time_raw)
                    start_time = t1.group(1) if t1 else ''
                    end_time = t2.group(1) if t2 else ''
                    
                    decimal_hours = parse_duration_to_decimal(duration)
                    
                    data.append({
                        'emp_id': current_emp_id,
                        'first_name': current_first_name,
                        'last_name': current_last_name,
                        'day': day_of_week,
                        'date': clean_date,
                        'start_time': start_time,
                        'end_time': end_time,
                        'type': entry_type.strip(),
                        'duration': duration,
                        'decimal_hours': decimal_hours,
                        'store_no': store_no
                    })

    return pd.DataFrame(data), store_no

# ==========================================
# 4. DATA GENERATION FUNCTIONS
# ==========================================

def generate_formatted_data(df, store_no):
    if df.empty: return pd.DataFrame()
    daily_df = df[df['type'].isin(['Clockset', 'Paid Break'])].copy()
    output_df = pd.DataFrame({
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
    return output_df

def generate_pivot_data(df, store_no, pay_period_start):
    if df.empty: return pd.DataFrame()
    reported_ot_df = df[df['type'] == 'Overtime_Reported'].copy()
    daily_clock_df = df[df['type'].isin(['Clockset', 'Paid Break'])].copy()
    if daily_clock_df.empty: return pd.DataFrame()

    daily_clock_df[['date_obj', 'week']] = daily_clock_df['date'].apply(
        lambda x: pd.Series(get_week_number(x, pay_period_start))
    )
    daily_clock_df = daily_clock_df[daily_clock_df['week'].notna()].copy()

    weekly_summary = daily_clock_df.groupby(['emp_id', 'first_name', 'last_name', 'week']).agg(
        weekly_hours=('decimal_hours', 'sum')
    ).reset_index()

    weekly_summary['calc_regular'] = weekly_summary['weekly_hours'].apply(lambda x: min(x, 40))
    weekly_summary['calc_overtime'] = weekly_summary['weekly_hours'].apply(lambda x: max(0, x - 40))

    pivot = weekly_summary.groupby(['emp_id', 'first_name', 'last_name']).agg(
        total_hours=('weekly_hours', 'sum'),
        regular=('calc_regular', 'sum'),
        overtime=('calc_overtime', 'sum')
    ).reset_index()

    if not reported_ot_df.empty:
        reported_ot_summary = reported_ot_df.groupby('emp_id').agg(
            reported_overtime=('decimal_hours', 'sum')
        ).reset_index()
        pivot = pd.merge(pivot, reported_ot_summary, on='emp_id', how='left')
        pivot['overtime'] = pivot['reported_overtime'].fillna(pivot['overtime'])
        pivot['regular'] = pivot['total_hours'] - pivot['overtime']
        pivot.drop(columns=['reported_overtime'], inplace=True)

    pivot['store_no'] = store_no
    pivot['name'] = ''
    pivot = pivot[['store_no', 'name', 'total_hours', 'regular', 'overtime', 'emp_id', 'first_name', 'last_name']]
    pivot.columns = ['store no', 'name', 'total', 'regular', 'overtime', 'id', 'first name', 'last name']
    cols = ['total', 'regular', 'overtime']
    pivot[cols] = pivot[cols].round(2)
    return pivot

def generate_wage_split_data(df, store_no, pay_period_start, wage_change_date):
    if df.empty: return pd.DataFrame()
    daily_clock_df = df[df['type'].isin(['Clockset', 'Paid Break'])].copy()
    reported_ot_df = df[df['type'] == 'Overtime_Reported'].copy()
    if daily_clock_df.empty: return pd.DataFrame()

    daily_clock_df[['date_obj', 'week']] = daily_clock_df['date'].apply(
        lambda x: pd.Series(get_week_number(x, pay_period_start))
    )
    daily_clock_df = daily_clock_df[daily_clock_df['week'].notna()].copy()
    
    # Convert wage_change_date to datetime for comparison
    wc_date = datetime.combine(wage_change_date, datetime.min.time())
    
    daily_clock_df['wage_period'] = daily_clock_df['date_obj'].apply(
        lambda x: '2025' if x < wc_date else '2026'
    )

    weekly_totals = daily_clock_df.groupby(['emp_id', 'first_name', 'last_name', 'week']).agg(
        weekly_total_hours=('decimal_hours', 'sum'),
        spans_wage_change=('wage_period', lambda x: x.nunique() > 1)
    ).reset_index()

    weekly_totals['weekly_regular_hours'] = weekly_totals['weekly_total_hours'].apply(lambda x: min(x, 40))
    weekly_totals['weekly_ot_hours'] = weekly_totals['weekly_total_hours'].apply(lambda x: max(0, x - 40))

    daily_clock_df = pd.merge(daily_clock_df, weekly_totals[['emp_id', 'week', 'weekly_total_hours', 'weekly_regular_hours', 'weekly_ot_hours']], on=['emp_id', 'week'], how='left')

    daily_clock_df['day_proportion'] = daily_clock_df.apply(
        lambda row: row['decimal_hours'] / row['weekly_total_hours'] if row['weekly_total_hours'] > 0 else 0, axis=1
    )
    daily_clock_df['day_regular_hours'] = daily_clock_df['day_proportion'] * daily_clock_df['weekly_regular_hours']
    daily_clock_df['day_ot_hours'] = daily_clock_df['day_proportion'] * daily_clock_df['weekly_ot_hours']

    wage_period_summary = daily_clock_df.groupby(['emp_id', 'first_name', 'last_name', 'wage_period']).agg(
        total_hours=('decimal_hours', 'sum'),
        regular_hours=('day_regular_hours', 'sum'),
        ot_hours=('day_ot_hours', 'sum')
    ).reset_index()

    if not reported_ot_df.empty:
        reported_ot_summary = reported_ot_df.groupby('emp_id').agg(reported_overtime=('decimal_hours', 'sum')).reset_index()
        calc_ot_totals = wage_period_summary.groupby('emp_id')['ot_hours'].sum().reset_index()
        calc_ot_totals.columns = ['emp_id', 'calc_ot_total']
        wage_period_summary = pd.merge(wage_period_summary, reported_ot_summary, on='emp_id', how='left')
        wage_period_summary = pd.merge(wage_period_summary, calc_ot_totals, on='emp_id', how='left')
        
        wage_period_summary['ot_ratio'] = wage_period_summary.apply(
            lambda row: row['ot_hours'] / row['calc_ot_total'] if row['calc_ot_total'] > 0 else 0, axis=1
        )
        wage_period_summary['final_ot'] = wage_period_summary.apply(
            lambda row: row['reported_overtime'] * row['ot_ratio'] if pd.notna(row['reported_overtime']) else row['ot_hours'], axis=1
        )
        wage_period_summary['final_regular'] = wage_period_summary['total_hours'] - wage_period_summary['final_ot']
        wage_period_summary['ot_hours'] = wage_period_summary['final_ot']
        wage_period_summary['regular_hours'] = wage_period_summary['final_regular']
        wage_period_summary.drop(columns=['reported_overtime', 'calc_ot_total', 'ot_ratio', 'final_ot', 'final_regular'], inplace=True)

    wage_period_summary.rename(columns={'regular_hours': 'regular', 'ot_hours': 'overtime'}, inplace=True)

    pivot_2025 = wage_period_summary[wage_period_summary['wage_period'] == '2025'][['emp_id', 'first_name', 'last_name', 'total_hours', 'regular', 'overtime']].copy()
    pivot_2025.columns = ['emp_id', 'first_name', 'last_name', 'total_hours_2025', 'regular_2025', 'overtime_2025']
    
    pivot_2026 = wage_period_summary[wage_period_summary['wage_period'] == '2026'][['emp_id', 'first_name', 'last_name', 'total_hours', 'regular', 'overtime']].copy()
    pivot_2026.columns = ['emp_id', 'first_name', 'last_name', 'total_hours_2026', 'regular_2026', 'overtime_2026']

    pivot_wide = pd.merge(pivot_2025, pivot_2026, on=['emp_id', 'first_name', 'last_name'], how='outer').fillna(0)
    pivot_wide.insert(0, 'store_no', store_no)
    pivot_wide.insert(1, 'name', '')
    pivot_wide.rename(columns={'emp_id': 'id', 'first_name': 'first name', 'last_name': 'last name'}, inplace=True)
    
    column_order = [
        'store_no', 'name', 'id', 'first name', 'last name',
        'total_hours_2025', 'regular_2025', 'overtime_2025',
        'total_hours_2026', 'regular_2026', 'overtime_2026'
    ]
    pivot_wide = pivot_wide[[c for c in column_order if c in pivot_wide.columns]]
    numeric_cols = [c for c in pivot_wide.columns if 'hours' in c or 'regular' in c or 'overtime' in c]
    pivot_wide[numeric_cols] = pivot_wide[numeric_cols].round(2)
    return pivot_wide

# ==========================================
# 5. STREAMLIT APP INTERFACE
# ==========================================

st.title("📊 Payroll & Timeclock Processor")
st.markdown("Upload multiple store CSV files, set your dates, and download a consolidated report in one click.")

# --- SIDEBAR INPUTS ---
st.sidebar.header("Configuration")

# Date Pickers
today = datetime.now()
pay_period_start = st.sidebar.date_input("Pay Period Start Date", value=today)
wage_change_active = st.sidebar.checkbox("Apply Wage Split?", value=False)
wage_change_date = None
if wage_change_active:
    wage_change_date = st.sidebar.date_input("Wage Change Date", value=datetime(2026, 1, 1))

# File Uploader
uploaded_files = st.file_uploader("Upload CSV Files (Select Multiple)", accept_multiple_files=True, type=['csv'])

# --- PROCESSING BUTTON ---
if st.button("Start Processing", type="primary"):
    if not uploaded_files:
        st.error("Please upload at least one CSV file.")
    else:
        store_data = {}
        processed_count = 0
        
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        # 1. READ AND PARSE FILES
        for i, uploaded_file in enumerate(uploaded_files):
            status_text.text(f"Processing {uploaded_file.name}...")
            
            # Read content as string
            try:
                stringio = io.StringIO(uploaded_file.getvalue().decode("utf-8"))
                content = stringio.read()
            except UnicodeDecodeError:
                # Fallback for other encodings if utf-8 fails
                stringio = io.StringIO(uploaded_file.getvalue().decode("latin-1"))
                content = stringio.read()

            file_format = detect_file_format(content)
            
            df = pd.DataFrame()
            store_no = None
            
            if file_format == 'payroll':
                df, store_no = parse_payroll_structure(content)
            elif file_format == 'timeclock':
                df, store_no = parse_timeclock_structure(content)
            
            if not df.empty and store_no:
                if store_no in store_data:
                    store_data[store_no] = pd.concat([store_data[store_no], df], ignore_index=True)
                else:
                    store_data[store_no] = df
                processed_count += 1
            
            # Update progress
            progress_bar.progress((i + 1) / len(uploaded_files))

        status_text.text("Generating reports...")
        
        # 2. GENERATE OUTPUTS
        all_formatted = []
        all_pivot = []
        all_wage_split = []

        for store_no in sorted(store_data.keys()):
            df = store_data[store_no]
            
            # Convert inputs to datetime for logic if they aren't already
            pp_start_dt = datetime.combine(pay_period_start, datetime.min.time())
            
            formatted_df = generate_formatted_data(df, store_no)
            pivot_df = generate_pivot_data(df, store_no, pp_start_dt)
            
            if not formatted_df.empty: all_formatted.append(formatted_df)
            if not pivot_df.empty: all_pivot.append(pivot_df)
            
            if wage_change_active and wage_change_date:
                wc_date_dt = datetime.combine(wage_change_date, datetime.min.time())
                wage_split_df = generate_wage_split_data(df, store_no, pp_start_dt, wage_change_date)
                if not wage_split_df.empty: all_wage_split.append(wage_split_df)

        # 3. CREATE ZIP FILE IN MEMORY
        if not all_formatted and not all_pivot:
            st.warning("No valid data was extracted. Please check your files.")
        else:
            zip_buffer = io.BytesIO()
            with zipfile.ZipFile(zip_buffer, "w") as zf:
                
                # Add Formatted CSV
                if all_formatted:
                    combined_formatted = pd.concat(all_formatted, ignore_index=True)
                    csv_data = combined_formatted.to_csv(index=False).encode('utf-8')
                    zf.writestr("All_Stores_Formatted.csv", csv_data)
                
                # Add Pivot CSV
                if all_pivot:
                    combined_pivot = pd.concat(all_pivot, ignore_index=True)
                    csv_data = combined_pivot.to_csv(index=False).encode('utf-8')
                    zf.writestr("All_Stores_Pivot.csv", csv_data)
                    
                # Add Wage Split CSV
                if all_wage_split:
                    combined_wage = pd.concat(all_wage_split, ignore_index=True)
                    csv_data = combined_wage.to_csv(index=False).encode('utf-8')
                    zf.writestr("All_Stores_WageSplit.csv", csv_data)
            
            st.success(f"Processing Complete! Processed {len(store_data)} stores.")
            
            # 4. DOWNLOAD BUTTON
            st.download_button(
                label="📥 Download Results (ZIP)",
                data=zip_buffer.getvalue(),
                file_name="payroll_results.zip",
                mime="application/zip"
            )

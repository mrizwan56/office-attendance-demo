
import sqlite3
from datetime import datetime
from pathlib import Path
from io import BytesIO

import pandas as pd
import streamlit as st

# -----------------------------
# Configuration
# -----------------------------
DB_PATH = Path("attendance.db")
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB

st.set_page_config(
    page_title="Office Attendance Register",
    page_icon="🏢",
    layout="wide",
)


# -----------------------------
# Database
# -----------------------------
def connect_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    with connect_db() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS attendance (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id TEXT NOT NULL,
                work_location TEXT NOT NULL,
                submitted_at TEXT NOT NULL,
                work_date TEXT NOT NULL,
                image_data BLOB,
                image_type TEXT,
                review_status TEXT NOT NULL DEFAULT 'Pending',
                review_note TEXT DEFAULT '',
                duplicate_flag INTEGER NOT NULL DEFAULT 0
            )
        """)
        conn.commit()


def save_submission(employee_id, location, image_data, image_type):
    now = datetime.now().astimezone()
    submitted_at = now.isoformat(timespec="seconds")
    work_date = now.date().isoformat()

    with connect_db() as conn:
        previous = conn.execute("""
            SELECT COUNT(*) FROM attendance
            WHERE employee_id = ? AND work_date = ?
        """, (employee_id, work_date)).fetchone()[0]

        duplicate_flag = 1 if previous > 0 else 0

        cursor = conn.execute("""
            INSERT INTO attendance (
                employee_id, work_location, submitted_at,
                work_date, image_data, image_type,
                review_status, duplicate_flag
            )
            VALUES (?, ?, ?, ?, ?, ?, 'Pending', ?)
        """, (
            employee_id, location, submitted_at, work_date,
            image_data, image_type, duplicate_flag
        ))
        conn.commit()
        return cursor.lastrowid, duplicate_flag


def load_records():
    with connect_db() as conn:
        return pd.read_sql_query("""
            SELECT id, employee_id, work_location,
                   submitted_at, work_date, review_status,
                   review_note, duplicate_flag
            FROM attendance
            ORDER BY id DESC
        """, conn)


def load_image(record_id):
    with connect_db() as conn:
        row = conn.execute("""
            SELECT image_data, image_type
            FROM attendance WHERE id = ?
        """, (record_id,)).fetchone()
    return row


def update_review(record_id, status, note):
    with connect_db() as conn:
        conn.execute("""
            UPDATE attendance
            SET review_status = ?, review_note = ?
            WHERE id = ?
        """, (status, note, record_id))
        conn.commit()


# Create database/table if needed
init_db()


# -----------------------------
# Application UI
# -----------------------------
st.title("🏢 Office Attendance Photo Register")
st.caption(
    "Prototype for employee-submitted attendance photos. "
    "A photo and employee ID are not independent identity "
    "or physical-location verification."
)

employee_tab, admin_tab = st.tabs([
    "Employee Check-in",
    "Admin Dashboard",
])


# -----------------------------
# Employee check-in
# -----------------------------
with employee_tab:
    st.subheader("Submit today's attendance")

    with st.form("attendance_form"):
        employee_id = st.text_input(
            "Employee ID",
            placeholder="Example: E101",
            max_chars=30,
        )

        location = st.selectbox(
            "Declared work location",
            ["Office", "Remote"],
        )

        st.write("Capture a check-in photo")
        photo = st.camera_input(
            "Open camera and capture a photo",
            key="attendance_camera",
        )

        uploaded_photo = st.file_uploader(
            "Or upload a photo",
            type=["jpg", "jpeg", "png"],
            key="attendance_upload",
        )

        st.caption(
            "Submit only a photo you are authorized to provide. "
            "The image is saved with your attendance record."
        )

        submitted = st.form_submit_button(
            "Submit attendance",
            type="primary",
            use_container_width=True,
        )

    if submitted:
        clean_id = employee_id.strip()

        if not clean_id:
            st.error("Please enter your employee ID.")
        elif photo is None and uploaded_photo is None:
            st.error("Please capture or upload a photo.")
        else:
            selected_photo = (
                uploaded_photo if uploaded_photo is not None
                else photo
            )

            image_bytes = selected_photo.getvalue()
            image_type = selected_photo.type or "image/jpeg"

            if image_type not in ("image/jpeg", "image/png"):
                st.error("Please submit a JPEG or PNG image.")
            elif len(image_bytes) > MAX_IMAGE_SIZE:
                st.error("The image is too large. Maximum size is 5 MB.")
            elif not image_bytes:
                st.error("The image is empty. Please try again.")
            else:
                try:
                    record_id, is_duplicate = save_submission(
                        clean_id,
                        location,
                        image_bytes,
                        image_type,
                    )

                    st.success(
                        f"Attendance submitted successfully. "
                        f"Record ID: {record_id}"
                    )
                    st.write(
                        "Submission time:",
                        datetime.now().astimezone().strftime(
                            "%Y-%m-%d %H:%M:%S %Z"
                        ),
                    )

                    if is_duplicate:
                        st.warning(
                            "A record already exists for this "
                            "employee and date. This submission "
                            "has been flagged for review."
                        )

                except sqlite3.Error:
                    st.error(
                        "The record could not be saved. "
                        "Please contact the administrator."
                    )


# -----------------------------
# Admin dashboard
# -----------------------------
with admin_tab:
    st.subheader("Attendance records")

    st.warning(
        "Demo limitation: this admin tab has no authentication. "
        "Do not expose this app to a team or public network until "
        "administrator access is protected."
    )

    records = load_records()

    if records.empty:
        st.info("No attendance records have been submitted yet.")
    else:
        total = len(records)
        pending = int(
            (records["review_status"] == "Pending").sum()
        )
        duplicates = int(records["duplicate_flag"].sum())

        c1, c2, c3 = st.columns(3)
        c1.metric("Total submissions", total)
        c2.metric("Pending review", pending)
        c3.metric("Duplicate flags", duplicates)

        dates = sorted(
            records["work_date"].dropna().unique().tolist(),
            reverse=True,
        )
        selected_date = st.selectbox(
            "Filter by submission date",
            ["All dates"] + dates,
        )

        filtered = records.copy()
        if selected_date != "All dates":
            filtered = filtered[
                filtered["work_date"] == selected_date
            ]

        st.dataframe(
            filtered.drop(columns=["duplicate_flag"]),
            use_container_width=True,
            hide_index=True,
        )

        csv_data = filtered.drop(
            columns=["duplicate_flag"]
        ).to_csv(index=False).encode("utf-8")

        st.download_button(
            "Download attendance CSV",
            data=csv_data,
            file_name="attendance_records.csv",
            mime="text/csv",
        )

        st.divider()
        st.subheader("Review individual submissions")

        record_options = {
            f"Record {row.id} | {row.employee_id} | "
            f"{row.work_date} | {row.review_status}": int(row.id)
            for row in filtered.itertuples()
        }

        if record_options:
            selected_label = st.selectbox(
                "Select a record",
                list(record_options.keys()),
            )
            record_id = record_options[selected_label]

            record = filtered[
                filtered["id"] == record_id
            ].iloc[0]

            st.write("Employee ID:", record["employee_id"])
            st.write("Declared location:", record["work_location"])
            st.write("Submitted at:", record["submitted_at"])
            st.write("Review status:", record["review_status"])

            if record["duplicate_flag"]:
                st.warning(
                    "Duplicate submission flag: another record "
                    "exists for this employee and date."
                )

            image_row = load_image(record_id)

            if image_row and image_row["image_data"]:
                st.image(
                    BytesIO(image_row["image_data"]),
                    caption=f"Submitted photo — record {record_id}",
                    width=350,
                )
            else:
                st.warning("No image is available for this record.")

            with st.form(f"review_form_{record_id}"):
                new_status = st.selectbox(
                    "Review decision",
                    ["Pending", "Reviewed", "Needs follow-up"],
                    index=(
                        ["Pending", "Reviewed", "Needs follow-up"]
                        .index(record["review_status"])
                        if record["review_status"]
                        in ["Pending", "Reviewed", "Needs follow-up"]
                        else 0
                    ),
                )

                note = st.text_area(
                    "Review note (optional)",
                    value=record["review_note"] or "",
                )

                save_review = st.form_submit_button(
                    "Save review"
                )

            if save_review:
                update_review(record_id, new_status, note)
                st.success("Review status saved.")
                st.rerun()

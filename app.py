
import hmac
import sqlite3
from datetime import datetime
from pathlib import Path
from io import BytesIO

import pandas as pd
import streamlit as st


# =========================================================
# CONFIGURATION
# =========================================================
DB_PATH = Path("attendance.db")
MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5 MB

st.set_page_config(
    page_title="Office Attendance Register",
    page_icon="🏢",
    layout="wide",
)


# =========================================================
# ADMIN AUTHENTICATION
# =========================================================
def require_admin():
    if st.session_state.get("admin_authenticated", False):
        return True

    st.subheader("Administrator access")

    with st.form("admin_login_form"):
        password = st.text_input(
            "Admin password",
            type="password",
        )
        login_clicked = st.form_submit_button("Unlock dashboard")

    if login_clicked:
        expected = st.secrets.get("ADMIN_PASSWORD", "")

        if expected and hmac.compare_digest(password, expected):
            st.session_state["admin_authenticated"] = True
            st.rerun()
        else:
            st.error("Incorrect password.")

    return False


# =========================================================
# DATABASE
# =========================================================
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
                employee_name TEXT NOT NULL DEFAULT '',
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

        # Safely add employee_name to an existing database.
        columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(attendance)"
            ).fetchall()
        }

        if "employee_name" not in columns:
            conn.execute("""
                ALTER TABLE attendance
                ADD COLUMN employee_name TEXT NOT NULL DEFAULT ''
            """)

        conn.commit()


def save_submission(
    employee_id,
    employee_name,
    location,
    image_data,
    image_type,
):
    now = datetime.now().astimezone()
    submitted_at = now.isoformat(timespec="seconds")
    work_date = now.date().isoformat()

    with connect_db() as conn:
        previous = conn.execute("""
            SELECT COUNT(*)
            FROM attendance
            WHERE employee_id = ? AND work_date = ?
        """, (employee_id, work_date)).fetchone()[0]

        duplicate_flag = 1 if previous > 0 else 0

        cursor = conn.execute("""
            INSERT INTO attendance (
                employee_id,
                employee_name,
                work_location,
                submitted_at,
                work_date,
                image_data,
                image_type,
                review_status,
                duplicate_flag
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, 'Pending', ?)
        """, (
            employee_id,
            employee_name,
            location,
            submitted_at,
            work_date,
            image_data,
            image_type,
            duplicate_flag,
        ))

        conn.commit()
        return cursor.lastrowid, duplicate_flag


def load_records():
    with connect_db() as conn:
        return pd.read_sql_query("""
            SELECT
                id,
                employee_id,
                employee_name,
                work_location,
                submitted_at,
                work_date,
                review_status,
                review_note,
                duplicate_flag
            FROM attendance
            ORDER BY id DESC
        """, conn)


def load_image(record_id):
    with connect_db() as conn:
        return conn.execute("""
            SELECT image_data, image_type
            FROM attendance
            WHERE id = ?
        """, (int(record_id),)).fetchone()


def update_review(record_id, status, note):
    with connect_db() as conn:
        conn.execute("""
            UPDATE attendance
            SET review_status = ?, review_note = ?
            WHERE id = ?
        """, (status, note, int(record_id)))
        conn.commit()


def delete_record(record_id):
    with connect_db() as conn:
        conn.execute(
            "DELETE FROM attendance WHERE id = ?",
            (int(record_id),),
        )
        conn.commit()


# Initialize or migrate the database.
init_db()


# =========================================================
# APPLICATION HEADER AND NAVIGATION
# =========================================================
st.title("🏢 Office Attendance Photo Register")
st.caption(
    "Attendance records contain employee-submitted information. "
    "An employee ID and photo alone do not independently verify "
    "identity or physical location."
)

page = st.radio(
    "Navigate",
    ["Employee Check-in", "Admin Dashboard"],
    horizontal=True,
)


# =========================================================
# EMPLOYEE CHECK-IN
# =========================================================
if page == "Employee Check-in":
    st.subheader("Submit today's attendance")

    with st.form("attendance_form"):
        employee_id = st.text_input(
            "Employee ID",
            placeholder="Example: E101",
            max_chars=30,
        )

        employee_name = st.text_input(
            "Employee Name",
            placeholder="Enter your full name",
            max_chars=100,
        )

        location = st.selectbox(
            "Declared work location",
            ["Office", "Remote"],
        )

        st.write("Capture a check-in photo")

        photo = st.camera_input(
            "Take a photo",
            key="attendance_camera",
        )

        uploaded_photo = st.file_uploader(
            "Or upload a photo",
            type=["jpg", "jpeg", "png"],
            key="attendance_upload",
        )

        st.caption(
            "Submit only a photo you are authorized to provide."
        )

        submitted = st.form_submit_button(
            "Submit attendance",
            type="primary",
            use_container_width=True,
        )

    if submitted:
        clean_id = employee_id.strip()
        clean_name = employee_name.strip()

        if not clean_id:
            st.error("Please enter your employee ID.")

        elif not clean_name:
            st.error("Please enter your employee name.")

        elif photo is None and uploaded_photo is None:
            st.error("Please capture or upload a photo.")

        else:
            selected_photo = (
                uploaded_photo
                if uploaded_photo is not None
                else photo
            )

            image_bytes = selected_photo.getvalue()
            image_type = selected_photo.type or "image/jpeg"

            if image_type not in ("image/jpeg", "image/png"):
                st.error("Please submit a JPEG or PNG image.")

            elif len(image_bytes) > MAX_IMAGE_SIZE:
                st.error("The image must be no larger than 5 MB.")

            elif not image_bytes:
                st.error("The image is empty. Please try again.")

            else:
                try:
                    record_id, is_duplicate = save_submission(
                        clean_id,
                        clean_name,
                        location,
                        image_bytes,
                        image_type,
                    )

                    st.success(
                        f"Attendance submitted successfully. "
                        f"Record ID: {record_id}"
                    )

                    if is_duplicate:
                        st.warning(
                            "A submission already exists for this "
                            "employee and date. This submission "
                            "has been flagged for review."
                        )

                except sqlite3.Error:
                    st.error(
                        "Could not save the attendance record. "
                        "Please contact the administrator."
                    )


# =========================================================
# ADMIN DASHBOARD
# =========================================================
else:
    if not require_admin():
        st.info(
            "Enter the administrator password to access "
            "attendance records and photos."
        )

    else:
        st.subheader("Attendance records")

        records = load_records()

        if records.empty:
            st.info("No attendance records have been submitted.")

        else:
            total = len(records)
            pending = int(
                (records["review_status"] == "Pending").sum()
            )
            duplicates = int(records["duplicate_flag"].sum())

            col1, col2, col3 = st.columns(3)
            col1.metric("Total submissions", total)
            col2.metric("Pending review", pending)
            col3.metric("Duplicate flags", duplicates)

            # Filter by work date.
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

            # Display records.
            display_columns = [
                "id",
                "employee_id",
                "employee_name",
                "work_location",
                "submitted_at",
                "work_date",
                "review_status",
                "review_note",
            ]

            st.dataframe(
                filtered[display_columns],
                use_container_width=True,
                hide_index=True,
            )

            # CSV export.
            csv_data = filtered[display_columns].to_csv(
                index=False
            ).encode("utf-8")

            st.download_button(
                "Download attendance CSV",
                data=csv_data,
                file_name="attendance_records.csv",
                mime="text/csv",
            )

            st.divider()
            st.subheader("Review individual submissions")

            record_options = {
                (
                    f"Record {row.id} | "
                    f"{row.employee_name or 'Name missing'} "
                    f"({row.employee_id}) | "
                    f"{row.work_date} | {row.review_status}"
                ): int(row.id)
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
                st.write(
                    "Employee Name:",
                    record["employee_name"] or "Not provided",
                )
                st.write(
                    "Declared location:",
                    record["work_location"],
                )
                st.write("Submitted at:", record["submitted_at"])
                st.write("Review status:", record["review_status"])

                if record["duplicate_flag"]:
                    st.warning(
                        "Duplicate submission flag: another record "
                        "exists for this employee and date."
                    )

                # Display the selected photo.
                image_row = load_image(record_id)

                if image_row and image_row["image_data"]:
                    st.image(
                        BytesIO(image_row["image_data"]),
                        caption=f"Submitted photo — record {record_id}",
                        width=350,
                    )
                else:
                    st.warning("No image is available for this record.")

                # Review form.
                with st.form(f"review_form_{record_id}"):
                    statuses = [
                        "Pending",
                        "Reviewed",
                        "Needs follow-up",
                    ]

                    current_status = record["review_status"]

                    status_index = (
                        statuses.index(current_status)
                        if current_status in statuses
                        else 0
                    )

                    new_status = st.selectbox(
                        "Review decision",
                        statuses,
                        index=status_index,
                    )

                    note = st.text_area(
                        "Review note (optional)",
                        value=record["review_note"] or "",
                    )

                    save_review = st.form_submit_button(
                        "Save review"
                    )

                if save_review:
                    update_review(
                        record_id,
                        new_status,
                        note,
                    )
                    st.success("Review status saved.")
                    st.rerun()

                # Delete selected record.
                st.divider()
                st.subheader("Delete attendance record")

                st.warning(
                    "Deleting this record permanently removes "
                    "its attendance details and stored photo."
                )

                with st.form(f"delete_form_{record_id}"):
                    confirm_delete = st.checkbox(
                        f"I confirm deletion of record {record_id}"
                    )

                    delete_clicked = st.form_submit_button(
                        "Delete this record",
                        type="primary",
                    )

                if delete_clicked:
                    if confirm_delete:
                        delete_record(record_id)
                        st.success(
                            f"Record {record_id} and its photo "
                            "have been deleted."
                        )
                        st.rerun()
                    else:
                        st.error(
                            "Please confirm deletion before proceeding."
                        )

        # Lock dashboard.
        st.divider()

        if st.button("Lock admin dashboard"):
            st.session_state["admin_authenticated"] = False
            st.rerun()

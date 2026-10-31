"""Clean the HR CSV files and save results without changing the source files.

Run with:
    python clean_hr_data.py

The script reads the five CSVs from SOURCE_DIR and creates a cleaned_output
folder beside the source files. Reviews dated before an employee's hire date
are written to a separate exceptions file and excluded from the cleaned
PerformanceRating.csv; no records are permanently deleted.
"""

from __future__ import annotations

import csv
import json
from collections import Counter
from datetime import datetime
from pathlib import Path



SOURCE_DIR = Path(r"D:\DEPI\final_project\Datasets\Data_Set_HR")
OUTPUT_DIR = SOURCE_DIR / "cleaned_output"

FILES = (
    "EducationLevel.csv",
    "Employee.csv",
    "PerformanceRating.csv",
    "RatingLevel.csv",
    "SatisfiedLevel.csv",
)


def read_csv(path: Path) -> tuple[list[str], list[dict[str, str]]]:

    with path.open("r", encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        if not reader.fieldnames:
            raise ValueError(f"CSV has no header: {path}")
        headers = [header.strip() for header in reader.fieldnames]
        rows: list[dict[str, str]] = []
        for source_row in reader:
            row = {}
            for old_name, new_name in zip(reader.fieldnames, headers):
                value = source_row.get(old_name)
                row[new_name] = value.strip() if value is not None else ""
            rows.append(row)
    return headers, rows


def remove_exact_duplicates(rows: list[dict[str, str]], headers: list[str]):
    """Keep the first copy of each fully identical row."""
    seen: set[tuple[str, ...]] = set()
    unique_rows = []
    duplicate_count = 0
    for row in rows:
        key = tuple(row.get(column, "") for column in headers)
        if key in seen:
            duplicate_count += 1
            continue
        seen.add(key)
        unique_rows.append(row)
    return unique_rows, duplicate_count


def write_csv(path: Path, headers: list[str], rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=headers, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def parse_date(value: str, column: str) -> datetime:
    """Parse known source formats, rejecting ambiguous/unexpected formats."""
    formats = ("%Y-%m-%d",) if column == "HireDate" else (
        "%m/%d/%Y",  # Format observed in PerformanceRating.csv
        "%Y-%m-%d",
    )
    for fmt in formats:
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            pass
    raise ValueError(f"Unrecognized {column} value: {value!r}")


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    data: dict[str, list[dict[str, str]]] = {}
    headers_by_file: dict[str, list[str]] = {}
    report: dict[str, object] = {"source_folder": str(SOURCE_DIR), "files": {}}

    # Read, trim text, and remove exact duplicate rows from each table.
    for filename in FILES:
        source_path = SOURCE_DIR / filename
        if not source_path.is_file():
            raise FileNotFoundError(f"Required input file not found: {source_path}")
        headers, rows = read_csv(source_path)
        rows, duplicate_count = remove_exact_duplicates(rows, headers)
        data[filename] = rows
        headers_by_file[filename] = headers
        report["files"][filename] = {
            "input_rows": sum(1 for _ in source_path.open("r", encoding="utf-8-sig")) - 1,
            "rows_after_exact_deduplication": len(rows),
            "exact_duplicate_rows_removed": duplicate_count,
            "blank_cells_after_trimming": sum(
                1 for row in rows for column in headers if not row.get(column, "").strip()
            ),
        }

    employees = data["Employee.csv"]
    performance = data["PerformanceRating.csv"]

    # Normalize dates in-place to ISO format. HireDate is already ISO in the
    # supplied files; ReviewDate is commonly M/D/YYYY.
    employee_by_id: dict[str, dict[str, str]] = {}
    duplicate_employee_ids: list[str] = []
    for employee in employees:
        employee_id = employee.get("EmployeeID", "")
        if employee_id in employee_by_id:
            duplicate_employee_ids.append(employee_id)
        else:
            employee_by_id[employee_id] = employee
        if employee.get("HireDate"):
            employee["HireDate"] = parse_date(employee["HireDate"], "HireDate").strftime("%Y-%m-%d")

    clean_performance: list[dict[str, str]] = []
    before_hire: list[dict[str, str]] = []
    orphan_performance: list[dict[str, str]] = []
    invalid_dates: list[dict[str, str]] = []

    for row in performance:
        employee = employee_by_id.get(row.get("EmployeeID", ""))
        try:
            if row.get("ReviewDate"):
                review_date = parse_date(row["ReviewDate"], "ReviewDate")
                row["ReviewDate"] = review_date.strftime("%Y-%m-%d")
            else:
                raise ValueError("ReviewDate is blank")
        except ValueError as error:
            invalid = dict(row)
            invalid["DataIssue"] = str(error)
            invalid_dates.append(invalid)
            continue

        if employee is None:
            orphan_performance.append(row)
            continue

        hire_date = parse_date(employee["HireDate"], "HireDate")
        if review_date < hire_date:
            flagged = dict(row)
            flagged["DataIssue"] = (
                f"ReviewDate {row['ReviewDate']} is before HireDate {employee['HireDate']}"
            )
            before_hire.append(flagged)
        else:
            clean_performance.append(row)

    # Check for employees who have no remaining valid performance reviews.
    reviewed_employee_ids = {row.get("EmployeeID", "") for row in clean_performance}
    employees_without_reviews = [
        {"EmployeeID": employee.get("EmployeeID", ""),
         "FirstName": employee.get("FirstName", ""),
         "LastName": employee.get("LastName", ""),
         "HireDate": employee.get("HireDate", "")}
        for employee in employees
        if employee.get("EmployeeID", "") not in reviewed_employee_ids
    ]

    # Write cleaned CSV tables. The anomalous rows remain available separately.
    for filename in FILES:
        rows = clean_performance if filename == "PerformanceRating.csv" else data[filename]
        write_csv(OUTPUT_DIR / filename, headers_by_file[filename], rows)

    perf_headers = headers_by_file["PerformanceRating.csv"]
    if before_hire:
        write_csv(OUTPUT_DIR / "reviews_before_hire_exceptions.csv",
                  perf_headers + ["DataIssue"], before_hire)
    if invalid_dates:
        write_csv(OUTPUT_DIR / "invalid_review_dates_exceptions.csv",
                  perf_headers + ["DataIssue"], invalid_dates)
    if orphan_performance:
        write_csv(OUTPUT_DIR / "unknown_employee_exceptions.csv",
                  perf_headers, orphan_performance)
    write_csv(OUTPUT_DIR / "employees_without_valid_reviews.csv",
              ["EmployeeID", "FirstName", "LastName", "HireDate"],
              employees_without_reviews)

    report["checks"] = {
        "employee_ids_are_unique": not duplicate_employee_ids,
        "duplicate_employee_ids": sorted(set(duplicate_employee_ids)),
        "reviews_before_hire_date_quarantined": len(before_hire),
        "invalid_or_blank_review_dates_quarantined": len(invalid_dates),
        "performance_rows_with_unknown_employee_id": len(orphan_performance),
        "employees_without_valid_reviews": len(employees_without_reviews),
        "clean_performance_rows_written": len(clean_performance),
        "date_format_in_outputs": "YYYY-MM-DD",
    }

    report_path = OUTPUT_DIR / "cleaning_report.json"
    report_path.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"Done. Cleaned files and reports are in:\n{OUTPUT_DIR}")
    print(f"Reviews before hire date moved to exceptions: {len(before_hire)}")
    print(f"Employees without valid reviews listed: {len(employees_without_reviews)}")
    print(f"Full summary: {report_path.name}")


if __name__ == "__main__":
    main()

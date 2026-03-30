from __future__ import annotations

from datetime import datetime, time
from typing import Any, List

from django.core.management.base import BaseCommand

from mcp_gateway.google_sheets_client import GoogleSheetsClient, GoogleSheetsClientError
from mcp_gateway.views import _parse_sheet_date

from crm.models import Customer


def _find_header_index(headers: List[str], candidates: List[str]) -> int | None:
    for cand in candidates:
        try:
            return headers.index(cand)
        except ValueError:
            # try case-insensitive match
            low = [h.lower() for h in headers]
            if cand.lower() in low:
                return low.index(cand.lower())
    return None


def _parse_bool(value: str) -> bool:
    v = (value or "").strip().lower()
    return v in {"1", "y", "yes", "true", "t"}


class Command(BaseCommand):
    help = "Sync customers from Google Sheet into the crm.Customer model"

    def add_arguments(self, parser):
        parser.add_argument("--range", dest="range", default="Customers!A:Z", help="Sheet range to read")
        parser.add_argument("--tag-column", dest="tag_column", default="Customer", help="Header name for customer tag")
        parser.add_argument("--dry-run", action="store_true", dest="dry_run", help="Do not write changes")

    def handle(self, *args: Any, **options: Any) -> None:
        range_name = options["range"]
        tag_column = options["tag_column"]
        dry_run = bool(options.get("dry_run", False))

        self.stdout.write(f"Reading sheet range: {range_name}")

        sheets = GoogleSheetsClient()
        try:
            payload = sheets.get_values(range_name=range_name, major_dimension="ROWS")
        except GoogleSheetsClientError as exc:
            msg = str(exc)
            if "Unable to parse range" in msg:
                # try to list available tabs to help the user choose the correct range
                try:
                    meta = sheets.get_spreadsheet()
                    tabs = [s.get("properties", {}).get("title") for s in meta.get("sheets", [])]
                except Exception:
                    tabs = []
                raise Exception(f"Google Sheets range parse error for '{range_name}'. Available tabs: {tabs}")
            raise Exception(f"Google Sheets error: {exc}")

        rows = payload.get("values", [])
        if not rows:
            self.stdout.write("No rows returned from sheet")
            return

        headers = [str(h).strip() for h in rows[0]]

        tag_index = _find_header_index(headers, [tag_column, "Tag", "Customer", "Customer Name", "Name"])
        name_index = _find_header_index(headers, ["Name", "Customer Name", "Customer"]) or tag_index
        remark_index = _find_header_index(headers, ["Remark", "Remarks", "Notes", "Comment", "Comments"])
        important_index = _find_header_index(headers, ["Important", "Flag", "Is Important", "Important?"])
        last_contact_index = _find_header_index(headers, ["Last Contact", "Last Contacted", "Contacted On", "Last Contact Date"])

        # Additional mappings from Customer_Master_QB
        external_id_index = _find_header_index(headers, ["Id", "ID", "External Id", "ExternalID"]) 
        company_index = _find_header_index(headers, ["Company name", "Company", "Organisation"]) 
        street_index = _find_header_index(headers, ["Street Address", "Address", "Street"]) 
        city_index = _find_header_index(headers, ["City"]) 
        state_index = _find_header_index(headers, ["State"]) 
        country_index = _find_header_index(headers, ["Country"]) 
        zip_index = _find_header_index(headers, ["Zip", "Zip Code", "Postal Code"]) 
        phone_index = _find_header_index(headers, ["Phone", "Phone Number"]) 
        mobile_index = _find_header_index(headers, ["Mobile", "Mobile Number", "Cell"]) 
        email_index = _find_header_index(headers, ["Email", "Email Address"]) 
        sheet_updated_index = _find_header_index(headers, ["Last Updated", "Updated On", "Updated At"]) 
        sheet_updated_by_index = _find_header_index(headers, ["Updated By", "UpdatedBy", "Updated By User"]) 

        if tag_index is None:
            raise Exception(f"Could not find tag column (tried {tag_column}). Headers: {headers}")

        created = 0
        updated = 0
        skipped = 0

        for row in rows[1:]:
            sheet_tag = str(row[tag_index]).strip() if tag_index < len(row) else ""
            if not sheet_tag:
                skipped += 1
                continue

            name = (str(row[name_index]).strip() if name_index is not None and name_index < len(row) else "") or sheet_tag
            remark = str(row[remark_index]).strip() if remark_index is not None and remark_index < len(row) else ""
            important_raw = str(row[important_index]).strip() if important_index is not None and important_index < len(row) else ""
            last_contact_raw = str(row[last_contact_index]).strip() if last_contact_index is not None and last_contact_index < len(row) else ""

            external_id = str(row[external_id_index]).strip() if external_id_index is not None and external_id_index < len(row) else ""
            company_name = str(row[company_index]).strip() if company_index is not None and company_index < len(row) else ""
            street_address = str(row[street_index]).strip() if street_index is not None and street_index < len(row) else ""
            city = str(row[city_index]).strip() if city_index is not None and city_index < len(row) else ""
            state = str(row[state_index]).strip() if state_index is not None and state_index < len(row) else ""
            country = str(row[country_index]).strip() if country_index is not None and country_index < len(row) else ""
            zip_code = str(row[zip_index]).strip() if zip_index is not None and zip_index < len(row) else ""
            phone = str(row[phone_index]).strip() if phone_index is not None and phone_index < len(row) else ""
            mobile = str(row[mobile_index]).strip() if mobile_index is not None and mobile_index < len(row) else ""
            email = str(row[email_index]).strip() if email_index is not None and email_index < len(row) else ""
            sheet_updated_raw = str(row[sheet_updated_index]).strip() if sheet_updated_index is not None and sheet_updated_index < len(row) else ""
            sheet_updated_by = str(row[sheet_updated_by_index]).strip() if sheet_updated_by_index is not None and sheet_updated_by_index < len(row) else ""

            last_contact_dt = None
            if last_contact_raw:
                d = _parse_sheet_date(last_contact_raw)
                if d:
                    last_contact_dt = datetime.combine(d, time.min)
                else:
                    try:
                        # try ISO datetime
                        last_contact_dt = datetime.fromisoformat(last_contact_raw)
                    except Exception:
                        last_contact_dt = None

            important = _parse_bool(important_raw)

            # try to find by sheet_tag then external id
            obj = None
            if sheet_tag:
                obj = Customer.objects.filter(sheet_tag=sheet_tag).first()
            if not obj and external_id:
                obj = Customer.objects.filter(external_id=external_id).first()
            if not obj and sheet_tag:
                obj = Customer.objects.filter(name=sheet_tag).first()
            if not obj:
                obj = Customer(sheet_tag=sheet_tag)
                created += 1
            else:
                updated += 1

            obj.name = name
            obj.remark = remark
            obj.important = important
            obj.last_contact = last_contact_dt

            obj.external_id = external_id
            obj.company_name = company_name
            obj.street_address = street_address
            obj.city = city
            obj.state = state
            obj.country = country
            obj.zip_code = zip_code
            obj.phone = phone
            obj.mobile = mobile
            obj.email = email
            obj.sheet_last_updated = None
            if sheet_updated_raw:
                d = _parse_sheet_date(sheet_updated_raw)
                if d:
                    obj.sheet_last_updated = datetime.combine(d, datetime.min.time())
                else:
                    try:
                        obj.sheet_last_updated = datetime.fromisoformat(sheet_updated_raw)
                    except Exception:
                        obj.sheet_last_updated = None
            obj.sheet_updated_by = sheet_updated_by

            if dry_run:
                self.stdout.write(f"[dry-run] Would save: {sheet_tag} -> name={name}, important={important}, last_contact={last_contact_dt}")
            else:
                obj.save()

        self.stdout.write(f"Done. created={created} updated={updated} skipped={skipped}")

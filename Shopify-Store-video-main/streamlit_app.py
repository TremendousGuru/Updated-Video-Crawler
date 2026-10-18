"""Streamlit Community Cloud interface for Outreach Studio."""
from __future__ import annotations

import asyncio
import csv
import hmac
import io
import json
import os
from datetime import datetime, timezone
from urllib.parse import quote

import streamlit as st
from streamlit.errors import StreamlitSecretNotFoundError

import httpx

from app import compose as composer
from app import db, ingest, pipeline


st.set_page_config(page_title="Outreach Studio", page_icon="✉️", layout="wide")


def config_value(name: str, default: str = "") -> str:
    value = os.environ.get(name)
    if value:
        return value
    try:
        return str(st.secrets.get(name, default))
    except StreamlitSecretNotFoundError:
        return default


def require_login() -> None:
    username = config_value("APP_USERNAME")
    password = config_value("APP_PASSWORD")
    if not username or not password.strip() or len(password) < 16:
        st.error(
            "App access is locked until APP_USERNAME and APP_PASSWORD are configured "
            "in Streamlit Cloud → Settings → Secrets. APP_PASSWORD must be at least 16 characters."
        )
        st.stop()

    if st.session_state.get("authenticated"):
        return

    st.title("Outreach Studio")
    st.caption("Sign in to access your outreach workspace.")
    with st.form("login"):
        entered_username = st.text_input("Username")
        entered_password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Sign in", type="primary")
    if submitted:
        if hmac.compare_digest(entered_username, username) and hmac.compare_digest(entered_password, password):
            st.session_state["authenticated"] = True
            st.rerun()
        st.error("Username or password is incorrect.")
    st.stop()


def load_settings() -> dict:
    settings = db.load_settings()
    key = config_value("OPENAI_API_KEY")
    if key:
        settings["api_key"] = key
    elif st.session_state.get("session_api_key"):
        settings["api_key"] = st.session_state["session_api_key"]
    return settings


def table_rows() -> list[dict]:
    return db.list_leads()


async def run_batch(ids: list[int], settings: dict) -> dict:
    run = pipeline.start_run(ids, settings)
    if run.task is None:
        raise RuntimeError("The crawl-and-compose job did not start.")

    total = len(ids)
    progress = st.progress(0.0, text=f"Starting work for {total} stores...")
    summary = st.empty()
    details = st.empty()
    id_set = set(ids)

    def refresh_progress() -> None:
        snapshot = run.snapshot()
        processed = snapshot["processed"]
        ratio = processed / total if total else 1.0
        progress.progress(
            ratio,
            text=f"Processed {processed} of {total} stores",
        )

        current_leads = [lead for lead in db.list_leads() if lead["id"] in id_set]
        status_counts: dict[str, int] = {}
        for lead in current_leads:
            status = lead.get("status", "unknown")
            status_counts[status] = status_counts.get(status, 0) + 1
        summary.caption(
            f"Ready: {status_counts.get('ready', 0)} · "
            f"Crawling: {status_counts.get('crawling', 0)} · "
            f"Composing: {status_counts.get('composing', 0)} · "
            f"Failed: {status_counts.get('failed', 0)}"
        )

        visible = [
            lead for lead in current_leads
            if lead.get("status") in {"pending", "crawling", "crawled", "composing", "ready", "failed"}
        ]
        priority = {
            "failed": 0,
            "crawling": 1,
            "composing": 1,
            "pending": 2,
            "crawled": 2,
            "ready": 3,
        }
        visible.sort(key=lambda lead: (priority.get(lead.get("status", ""), 4), lead["id"]))
        visible = visible[:30]
        if visible:
            details.dataframe(
                [{
                    "Store": lead.get("store_name") or lead.get("domain") or f"Lead {lead['id']}",
                    "Status": lead.get("status", ""),
                    "Stage": lead.get("stage", ""),
                    "Details": lead.get("error") or lead.get("engine", ""),
                } for lead in visible],
                hide_index=True,
                use_container_width=True,
            )
        else:
            details.empty()

    refresh_progress()
    while not run.task.done():
        await asyncio.wait({run.task}, timeout=0.75)
        refresh_progress()
    await run.task
    refresh_progress()
    return run.snapshot()


def run_ids(ids: list[int], settings: dict) -> dict:
    return asyncio.run(run_batch(ids, settings))


def next_ready_lead_id(leads: list[dict], current_id: int) -> int | None:
    ready_ids = sorted(
        lead["id"] for lead in leads
        if lead.get("status") == "ready" and lead["id"] != current_id
    )
    return next(
        (lead_id for lead_id in ready_ids if lead_id > current_id),
        ready_ids[0] if ready_ids else None,
    )


def run_api_key_test(settings: dict) -> dict:
    return asyncio.run(composer.test_api_key(settings))


def export_csv(leads: list[dict]) -> str:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["email", "store_name", "domain", "subject", "body", "status", "engine", "hook", "sent_at"])
    for lead in leads:
        full = db.get_lead(lead["id"], full=True) or {}
        writer.writerow([
            lead.get("email", ""), lead.get("store_name", ""), lead.get("domain", ""),
            lead.get("subject", ""), full.get("body", ""), lead.get("status", ""),
            lead.get("engine", ""), lead.get("notes", ""), lead.get("sent_at", ""),
        ])
    return output.getvalue()


def export_json(leads: list[dict]) -> str:
    rows = []
    for lead in leads:
        full = db.get_lead(lead["id"], full=True) or {}
        rows.append({
            "to": lead.get("email", ""), "store_name": lead.get("store_name", ""),
            "domain": lead.get("domain", ""), "subject": lead.get("subject", ""),
            "body": full.get("body", ""), "subjects": lead.get("subjects", []),
            "engine": lead.get("engine", ""), "hook": lead.get("notes", ""),
            "status": lead.get("status", ""), "facts": full.get("facts", {}),
        })
    return json.dumps(rows, indent=2)


def save_settings_form(settings: dict) -> None:
    st.sidebar.header("Settings")
    with st.sidebar.form("settings"):
        sender_name = st.text_input("Your name", value=settings.get("sender_name", ""))
        sender_company = st.text_input("Company", value=settings.get("sender_company", ""))
        offer = st.text_input(
            "What you do",
            value=settings.get("offer", ""),
            help="Describe your service plainly. The draft will connect it to one observed product opportunity.",
        )
        video_line = st.text_input(
            "Video offer line",
            value=settings.get("video_line", ""),
            help="Describe a possible next step. Avoid suggesting a sample video has already been made.",
        )
        cta = st.text_input(
            "Call to action",
            value=settings.get("cta", ""),
            help="Keep the invitation low-pressure and tied to the storyboard or concept.",
        )
        subject_hint = st.text_input(
            "First subject idea",
            value=settings.get("subject_hint", ""),
            help="Use {product} to insert the selected product name into the subject.",
        )
        tone = st.text_input(
            "Tone",
            value=settings.get("tone", ""),
            help="Guides both AI-written and local fallback drafts.",
        )
        optout = st.checkbox("Include opt-out line", value=bool(settings.get("optout", True)))
        optout_line = st.text_input("Opt-out line", value=settings.get("optout_line", ""))
        st.divider()
        st.subheader("AI writing (optional)")
        base_url = st.text_input("OpenAI-compatible base URL", value=settings.get("base_url", ""))
        model = st.text_input("Model", value=settings.get("model", ""))
        st.caption("Set OPENAI_API_KEY in Streamlit Secrets for a persistent, private key.")
        api_key = st.text_input("Temporary API key for this session", type="password")
        use_ai = st.checkbox("Use AI when a key is available", value=bool(settings.get("use_ai", True)))
        respect_robots = st.checkbox("Respect robots.txt", value=bool(settings.get("respect_robots", True)))
        find_missing_emails = st.checkbox(
            "Look for missing email addresses", value=bool(settings.get("find_missing_emails", True))
        )
        auto_compose = st.checkbox("Write drafts after crawling", value=bool(settings.get("auto_compose", True)))
        concurrency = st.slider("Stores at once", 1, 10, int(settings.get("concurrency", 3)))
        request_delay = st.number_input(
            "Delay between requests (seconds)", min_value=0.0, max_value=10.0,
            value=float(settings.get("request_delay", 0.75)), step=0.1,
        )
        max_pages = st.slider("Maximum pages per store", 1, 15, int(settings.get("max_pages", 10)))
        submitted = st.form_submit_button("Save settings", type="primary")

    if submitted:
        db.save_settings({
            "sender_name": sender_name, "sender_company": sender_company, "offer": offer,
            "video_line": video_line, "cta": cta, "subject_hint": subject_hint, "tone": tone,
            "optout": optout, "optout_line": optout_line, "base_url": base_url,
            "model": model, "use_ai": use_ai, "respect_robots": respect_robots,
            "find_missing_emails": find_missing_emails, "auto_compose": auto_compose,
            "concurrency": concurrency, "request_delay": request_delay, "max_pages": max_pages,
        })
        if api_key.strip():
            st.session_state["session_api_key"] = api_key.strip()
        st.success("Settings saved.")
        st.rerun()

    secret_api_key = config_value("OPENAI_API_KEY").strip()
    active_api_key = (settings.get("api_key") or "").strip()
    if secret_api_key:
        st.sidebar.success("OPENAI_API_KEY detected in Streamlit Secrets.")
    elif st.session_state.get("session_api_key"):
        st.sidebar.info("A temporary API key is active for this session.")
    elif active_api_key:
        st.sidebar.info("An API key is available from saved settings.")
    else:
        st.sidebar.warning("Local mode: no API key detected. Evidence-based templates will be used; crawling still works.")

    if st.sidebar.button("Test API key", disabled=not active_api_key, key="test_api_key"):
        with st.sidebar.spinner("Testing the configured API key..."):
            try:
                result = run_api_key_test(settings)
            except (httpx.HTTPError, RuntimeError, ValueError) as exc:
                st.sidebar.error(f"API key test failed: {exc}")
            else:
                st.sidebar.success(f"API key works ({result['engine']}).")
                if result.get("sample"):
                    st.sidebar.caption(f"Sample response: {result['sample']}")


def main() -> None:
    require_login()
    st.title("Outreach Studio")
    st.caption("Upload stores → crawl → review personalized drafts → open in your email app.")

    settings = load_settings()
    save_settings_form(settings)
    leads = table_rows()

    counts = {}
    for lead in leads:
        counts[lead["status"]] = counts.get(lead["status"], 0) + 1
    metric_cols = st.columns(4)
    metric_cols[0].metric("Stores", len(leads))
    metric_cols[1].metric("Ready", counts.get("ready", 0))
    metric_cols[2].metric("Sent", counts.get("sent", 0))
    metric_cols[3].metric("Failed", counts.get("failed", 0))

    upload_tab, leads_tab, exports_tab = st.tabs(["Add stores", "Leads", "Export"])
    with upload_tab:
        st.subheader("Add your store list")
        files = st.file_uploader(
            "Upload CSV, XLSX or TXT", type=["csv", "tsv", "txt", "xlsx", "xlsm", "xls"], accept_multiple_files=True
        )
        pasted = st.text_area("Or paste rows (email, domain, and store name; one store per line)")
        if st.button("Add stores", type="primary"):
            parsed: list[dict] = []
            reports = []
            for file in files or []:
                try:
                    rows = ingest.parse_file(file.name, file.getvalue())
                    parsed.extend(rows)
                    reports.append(f"{file.name}: {len(rows)} rows read")
                except (ValueError, OSError) as exc:
                    reports.append(f"{file.name}: {exc}")
            if pasted.strip():
                rows = ingest.parse_pasted(pasted)
                parsed.extend(rows)
                reports.append(f"Pasted text: {len(rows)} rows read")
            added = db.insert_leads(parsed) if parsed else []
            for report in reports:
                st.write(report)
            if added:
                st.success(f"Added {len(added)} new stores (duplicates skipped).")
            elif not parsed:
                st.warning("No usable rows found. Each row needs an email address and/or store domain.")
            else:
                st.info("No new stores were added; all entries may already be in the list.")
            st.rerun()
        st.download_button(
            "Download CSV template",
            data="email,domain,store_name\nhello@example.com,example.com,Example Store\n",
            file_name="leads-template.csv",
            mime="text/csv",
        )
        if st.button("Load example stores"):
            examples = ingest.parse_pasted(
                "hello@deathwishcoffee.com, deathwishcoffee.com, Death Wish Coffee\n"
                "browngirljane.com\n"
                "hello@allbirds.com | allbirds.com | Allbirds\n"
                "hi@bombas.com, bombas.com\n"
                "contact@gingerpeople.com, gingerpeople.com"
            )
            db.insert_leads(examples)
            st.rerun()

    with leads_tab:
        st.subheader("Crawl and compose")
        if not leads:
            st.info("Add a list of stores to get started.")
        else:
            advance_action = st.session_state.pop("advance_to_ready", None)
            if advance_action is not None:
                st.session_state["lead_view"] = "Ready"
                if advance_action["next_id"] is None:
                    st.session_state.pop("review_lead_id", None)
                else:
                    st.session_state["review_lead_id"] = advance_action["next_id"]

            lead_view = st.selectbox(
                "Show leads", ["All", "Pending", "Ready", "Sent", "Failed"], key="lead_view"
            )
            if advance_action is not None:
                if advance_action["next_id"] is None:
                    st.success("Marked sent. There are no more Ready drafts.")
                else:
                    st.success("Marked sent. The next Ready draft is loaded below.")
            view_statuses = {
                "Pending": {"pending", "crawled", "crawling", "composing"},
                "Ready": {"ready"},
                "Sent": {"sent"},
                "Failed": {"failed"},
            }
            visible_leads = [
                lead for lead in leads
                if lead_view == "All" or lead.get("status") in view_statuses[lead_view]
            ]

            scope = st.selectbox("Crawl", ["Queued and failed", "Failed only", "All stores"])
            status_filter = {
                "Queued and failed": ["pending", "failed"],
                "Failed only": ["failed"],
                "All stores": None,
            }[scope]
            ids = db.lead_ids(statuses=status_filter)
            if st.button("Crawl & compose", type="primary", disabled=not ids):
                with st.spinner(f"Processing {len(ids)} stores..."):
                    result = run_ids(ids, settings)
                st.success(f"Finished: {result['ready']} ready, {result['failed']} failed.")
                st.rerun()

            frame = [{
                "Store": lead.get("store_name") or "—", "Domain": lead.get("domain", ""),
                "Email": lead.get("email", ""), "Status": lead.get("status", ""),
                "Details": lead.get("error") or lead.get("notes") or lead.get("engine", ""),
            } for lead in visible_leads]
            if not visible_leads:
                st.info(f"No {lead_view.lower()} leads.")
                selected_ids = []
            else:
                selection = st.dataframe(
                    frame, hide_index=True, use_container_width=True,
                    on_select="rerun", selection_mode="multi-row", key="lead_table",
                )
                selected_rows = selection.selection.rows
                selected_ids = [
                    visible_leads[index]["id"]
                    for index in selected_rows
                    if index < len(visible_leads)
                ]
            action_cols = st.columns(3)
            with action_cols[0]:
                if st.button("Crawl selected", disabled=not selected_ids):
                    with st.spinner(f"Processing {len(selected_ids)} stores..."):
                        result = run_ids(selected_ids, settings)
                    st.success(f"Finished: {result['ready']} ready, {result['failed']} failed.")
                    st.rerun()
            with action_cols[1]:
                if st.button("Delete all leads"):
                    st.session_state["confirm_delete"] = True
            with action_cols[2]:
                st.caption(f"{len(selected_ids)} selected")
            if st.session_state.get("confirm_delete"):
                st.warning("This permanently deletes the lead list and all drafts.")
                confirm_col, cancel_col = st.columns(2)
                with confirm_col:
                    if st.button("Confirm delete", type="primary"):
                        db.clear_leads()
                        st.session_state.pop("confirm_delete", None)
                        st.rerun()
                with cancel_col:
                    if st.button("Cancel delete"):
                        st.session_state.pop("confirm_delete", None)
                        st.rerun()

            st.divider()
            if visible_leads:
                lead_by_id = {lead["id"]: lead for lead in visible_leads}
                chosen_id = st.selectbox(
                    "Review a lead",
                    options=[lead["id"] for lead in visible_leads],
                    format_func=lambda lead_id: (
                        lead_by_id[lead_id].get("store_name")
                        or lead_by_id[lead_id].get("domain")
                        or str(lead_id)
                    ),
                    key="review_lead_id",
                )
                show_lead(lead_by_id[chosen_id], settings)
            elif lead_view == "Ready":
                st.info("No Ready drafts. Crawl and compose leads to create drafts.")

    with exports_tab:
        st.subheader("Export drafts")
        all_leads = table_rows()
        ready_leads = [lead for lead in all_leads if lead.get("status") in {"ready", "sent"}]
        export_scope = st.radio("Include", ["Ready and sent", "All leads"], horizontal=True)
        export_leads = ready_leads if export_scope == "Ready and sent" else all_leads
        st.download_button(
            "Export CSV", data=export_csv(export_leads), file_name="personalized-messages.csv", mime="text/csv"
        )
        st.download_button(
            "Export JSON", data=export_json(export_leads), file_name="personalized-messages.json",
            mime="application/json",
        )


def show_lead(lead: dict, settings: dict) -> None:
    full = db.get_lead(lead["id"], full=True) or {}
    st.markdown(f"### {lead.get('store_name') or lead.get('domain') or 'Store'}")
    st.write(f"**Email:** {lead.get('email') or 'No email found'}  ·  **Status:** {lead.get('status', '')}")
    if lead.get("error"):
        st.error(lead["error"])
    if lead.get("flags"):
        st.caption(" · ".join(lead["flags"]))
    if full.get("notes"):
        st.caption(f"Composition note: {full['notes']}")
    engine = str(full.get("engine") or lead.get("engine") or "")
    if engine == "evidence-template":
        if "AI fallback:" in str(full.get("notes") or ""):
            st.warning("The AI request failed. This draft was composed locally from the crawl evidence.")
        else:
            st.info("This draft was composed locally from crawl evidence; no AI API key was used.")
    elif engine.startswith("ai:"):
        st.caption(f"Composition engine: {engine}")

    subjects = full.get("subjects") or []
    selected_subject = st.selectbox(
        "Subject", options=[""] + subjects, index=(subjects.index(full.get("subject")) + 1)
        if full.get("subject") in subjects else 0, key=f"subject_{lead['id']}",
    )
    subject = st.text_input("Edit subject", value=selected_subject or full.get("subject", ""), key=f"edit_subject_{lead['id']}")
    body = st.text_area("Message draft", value=full.get("body", ""), height=240, key=f"body_{lead['id']}")

    already_sent = lead.get("status") == "sent"
    can_send = bool(
        lead.get("status") == "ready"
        and lead.get("email")
        and subject.strip()
        and body.strip()
    )
    if not already_sent and can_send:
        mailto = f"mailto:{quote(lead['email'], safe='')}?subject={quote(subject)}&body={quote(body)}"
        st.link_button("1. Open draft in Gmail", mailto)
        st.caption(
            "Send the message in Gmail, return here, then use **Sent & Next** to record it and load "
            "the next Ready draft. The website cannot verify whether Gmail actually sent it."
        )

    buttons = st.columns(4)
    with buttons[0]:
        if st.button("Save draft", key=f"save_{lead['id']}"):
            db.update_lead(lead["id"], subject=subject, body=body)
            st.success("Draft saved.")
            st.rerun()
    with buttons[1]:
        if st.button("Rewrite this one", key=f"rewrite_{lead['id']}"):
            db.update_lead(lead["id"], subject=subject, body=body)
            with st.spinner("Rewriting this message..."):
                result = run_ids([lead["id"]], settings)
            st.success(f"Rewrite finished: {result['ready']} ready, {result['failed']} failed.")
            st.rerun()
    with buttons[2]:
        if st.button("Re-crawl site", key=f"recrawl_{lead['id']}"):
            db.update_lead(lead["id"], facts="", status="pending")
            with st.spinner("Re-crawling this store..."):
                result = run_ids([lead["id"]], settings)
            st.success(f"Crawl finished: {result['ready']} ready, {result['failed']} failed.")
            st.rerun()
    with buttons[3]:
        if not already_sent and st.button(
            "2. Sent & Next",
            key=f"sent_{lead['id']}",
            disabled=not can_send,
        ):
            next_id = next_ready_lead_id(db.list_leads(), lead["id"])
            db.update_lead(lead["id"], subject=subject, body=body, status="sent",
                           sent_at=datetime.now(timezone.utc).isoformat(timespec="seconds"))
            st.session_state["advance_to_ready"] = {"next_id": next_id}
            st.rerun()

    if already_sent:
        sent_at = lead.get("sent_at")
        st.info(
            f"Marked sent{f' on {sent_at}' if sent_at else ''}. "
            "This records your confirmation; the website cannot verify delivery through Gmail."
        )
    elif not can_send:
        st.caption(
            "Add a recipient email, subject, and message body to enable the Gmail draft and Sent & Next actions."
        )

    facts = full.get("facts") or {}
    if facts:
        with st.expander("What we found"):
            st.json(facts)

        intelligence = composer.compose_store_intelligence(facts, settings)
        quality = intelligence.get("quality_control") or {}
        with st.expander("Store intelligence"):
            if intelligence.get("diagnosis", {}).get("primary_opportunity"):
                st.markdown("**Primary opportunity:** " + intelligence["diagnosis"]["primary_opportunity"])
                st.markdown("**Why video may help:** " + (intelligence["diagnosis"].get("reason_video_may_help") or "No clear reason yet."))
                st.markdown("**Recommended format:** " + (intelligence["video_brief"].get("format") or "Not selected"))
                st.markdown("**Selected product:** " + (intelligence["product_selection"].get("product_name") or "Not selected"))
                selection = intelligence.get("product_selection") or {}
                st.markdown(
                    f"**Prospect score:** {selection.get('score', 0)}/10 · "
                    f"{(selection.get('selection_status') or 'needs review').replace('_', ' ')}"
                )
                if selection.get("score_breakdown"):
                    st.caption("Score breakdown")
                    st.json(selection["score_breakdown"])
                if selection.get("alternative_candidates"):
                    st.caption("Other candidates requiring review")
                    st.json(selection["alternative_candidates"])
                if intelligence["diagnosis"].get("confidence") is not None:
                    st.caption(
                        "Opportunity confidence: "
                        + f"{intelligence['diagnosis'].get('confidence', 0):.0%}"
                    )
                if intelligence.get("outreach", {}).get("subject") or intelligence.get("outreach", {}).get("message"):
                    st.markdown("**Outreach subject:** " + (intelligence["outreach"].get("subject") or ""))
                    st.write(intelligence["outreach"].get("message") or "")
                evidence = intelligence["diagnosis"].get("evidence") or []
                if evidence:
                    st.caption("Evidence and inference used")
                    st.json(evidence)
                if quality.get("manual_review_required"):
                    st.warning("Manual review recommended: " + "; ".join(quality.get("review_reasons") or ["evidence is weak"]))
            else:
                st.info("No strong video opportunity was identified from the current evidence.")
            st.json(intelligence)

    pages = facts.get("pages_crawled") or []
    if pages:
        with st.expander("Sources"):
            for page in pages:
                st.markdown(f"- HTTP {page.get('status', '—')} · [{page.get('label', 'Page')}]({page.get('url', '')})")


main()

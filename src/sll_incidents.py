"""Explicit desktop self-responses using the PBX's recipient-authorized contract."""
from __future__ import annotations

import queue
import re
import threading


RESPONSES = {"received": "I have read this", "safe": "I am safe", "needs_assistance": "I need assistance"}
SERVER_RESPONSE_LABELS = {**RESPONSES, "missing": "Operator marked this participant missing"}


def incident_id(value: object) -> str:
    if not isinstance(value, str) or not re.fullmatch(r"inc_[a-f0-9]{32}", value):
        raise ValueError("Invalid incident identifier")
    return value


def response_incident(payload: object) -> str:
    """Only the explicit schema-1 incident object enables human-response UI.

    Unknown future metadata leaves the announcement readable. This metadata
    never cancels, supersedes, or acknowledges the notification itself.
    """
    metadata = payload.get("incident") if isinstance(payload, dict) else None
    if (not isinstance(metadata, dict) or type(metadata.get("schema")) is not int
            or metadata["schema"] != 1 or type(metadata.get("sequence")) is not int
            or not 1 <= metadata["sequence"] <= 250
            or not isinstance(metadata.get("kind"), str)
            or metadata.get("kind") not in {"initial", "update", "all_clear", "escalation"}
            or not isinstance(metadata.get("severity"), str)
            or metadata.get("severity") not in {"information", "warning", "critical"}
            or type(metadata.get("is_test")) is not bool
            or type(payload.get("is_test")) is not bool
            or payload["is_test"] != metadata["is_test"]):
        return ""
    try:
        return incident_id(metadata.get("incident_id"))
    except ValueError:
        return ""


def validate_projection(value: object, expected_id: str, username: str) -> dict:
    if (not isinstance(value, dict) or value.get("ok") is not True
            or value.get("success") is not True or type(value.get("schema")) is not int
            or value["schema"] != 1 or value.get("id") != expected_id
            or value.get("state") not in {"open", "closed", "planned", "missed"}
            or type(value.get("is_test")) is not bool):
        raise ValueError("The PBX did not confirm authorized incident details")
    person = value.get("person")
    if not isinstance(person, dict) or person.get("desktop_username") != username:
        raise ValueError("The PBX returned an incident for a different desktop")
    title = value.get("title")
    if not isinstance(title, str) or len(title) > 500:
        raise ValueError("Invalid incident title")
    response = value.get("response")
    if response is not None and (not isinstance(response, dict)
            or not isinstance(response.get("response"), str) or response["response"] not in SERVER_RESPONSE_LABELS):
        raise ValueError("The PBX returned an unsupported human response")
    # Keep only what this UI needs. Do not retain the person record or timeline.
    return {"id": expected_id, "title": title, "state": value["state"],
            "is_test": value["is_test"], "response": response.get("response", "") if response else ""}


class IncidentClient:
    def __init__(self, request, inbox, namespace: str, username: str, identifier: str):
        self.request, self.inbox, self.namespace, self.username = request, inbox, namespace, username
        self.identifier = incident_id(identifier)

    def details(self) -> dict:
        value = self.request("GET", "/api/sipnotify/desktop/incident?incident_id=" + self.identifier, None)
        return validate_projection(value, self.identifier, self.username)

    def pending(self) -> dict | None:
        return self.inbox.pending_human_response(self.namespace, self.identifier)

    def respond(self, response: str) -> dict:
        if response not in RESPONSES:
            raise ValueError("Unsupported incident response")
        # Save the exact request before network I/O. Only deliberate retries
        # resend it; no background worker replays a person's safety response.
        request = self.inbox.begin_human_response(self.namespace, self.identifier, response)
        value = self.request("POST", "/api/sipnotify/desktop/incident/respond", {
            "incident_id": self.identifier, "request_id": request["request_id"], "response": response,
        })
        projection = validate_projection(value, self.identifier, self.username)
        if projection["response"] != response:
            raise ValueError("The PBX has not confirmed this human response; retry the saved request")
        self.inbox.confirm_human_response(request["request_id"])
        return projection


class IncidentResponseWindow:
    """Network calls stay on one worker; every widget update stays on Tk."""
    def __init__(self, root, client: IncidentClient):
        import tkinter as tk
        from tkinter import ttk
        from sll_windowing import fit_window

        self.client = client
        self.events = queue.Queue(maxsize=1)
        self.busy = False
        self.projection = None
        self.window = tk.Toplevel(root)
        self.window.withdraw()
        self.window.title("Incident response")
        self.window.protocol("WM_DELETE_WINDOW", self.close)
        body = ttk.Frame(self.window, padding=18)
        body.pack(fill="both", expand=True)
        self.heading = ttk.Label(body, text="Checking your incident assignment...", wraplength=480,
                                 font=("Segoe UI", 13, "bold"))
        self.heading.pack(fill="x", pady=(0, 12))
        self.status = tk.StringVar(value="Loading authorized incident details from the PBX.")
        ttk.Label(body, textvariable=self.status, wraplength=480).pack(fill="x", pady=(0, 12))
        self.buttons = {}
        for value, label in RESPONSES.items():
            button = ttk.Button(body, text=label, command=lambda value=value: self.submit(value), state="disabled")
            button.pack(fill="x", pady=4)
            self.buttons[value] = button
        self.refresh = ttk.Button(body, text="Refresh", command=self.load)
        self.refresh.pack(side="left", pady=(12, 0))
        ttk.Button(body, text="Close", command=self.close).pack(side="right", pady=(12, 0))
        fit_window(self.window, (540, 360), minimum=(320, 300))
        self.window.deiconify()
        self.load()
        self.window.after(100, self.poll)

    def _start(self, operation, response=""):
        if self.busy:
            return
        self.busy = True
        self.refresh.configure(state="disabled")
        for button in self.buttons.values():
            button.configure(state="disabled")

        def run():
            try:
                result, error = operation(), ""
            except Exception as exc:
                result, error = None, str(exc)
            self.events.put((result, error, response))
        threading.Thread(target=run, name="IncidentResponse", daemon=True).start()

    def load(self):
        self.status.set("Checking your incident assignment...")
        self._start(self.client.details)

    def submit(self, response):
        self.status.set("Sending your response to the PBX...")
        self._start(lambda: self.client.respond(response), response)

    def poll(self):
        if not self.window.winfo_exists():
            return
        try:
            projection, error, submitted = self.events.get_nowait()
        except queue.Empty:
            pass
        else:
            self.busy = False
            self.refresh.configure(state="normal")
            if projection is not None:
                self.projection = projection
                marker = "DRILL / TEST: " if projection["is_test"] else ""
                self.heading.configure(text=marker + projection["title"])
                response = projection["response"]
                self.status.set(("PBX confirmed: " + SERVER_RESPONSE_LABELS[response] + ".") if response else "Choose a response to send to the PBX.")
                if projection["state"] != "open":
                    self.status.set("This incident is " + projection["state"] + ". New responses are unavailable.")
            else:
                self.status.set(("Response unconfirmed. " if submitted else "Unable to load incident. ") + error[:300])
            try:
                pending = self.client.pending()
            except Exception:
                pending = None
                self.projection = None
                self.status.set("Saved response state is unavailable. Close this window and review Health.")
            if pending:
                self.status.set("A previous response is unconfirmed. Retry it using the same saved request.")
            for response, button in self.buttons.items():
                can_answer = bool(self.projection and self.projection["state"] == "open")
                # An ambiguous request can be retried after closure: the server
                # recognizes duplicate request IDs before rejecting new actions.
                enabled = pending["response"] == response if pending else can_answer
                button.configure(state="normal" if enabled else "disabled",
                                 text=("Retry: " if pending and pending["response"] == response else "") + RESPONSES[response])
        self.window.after(100, self.poll)

    def close(self):
        if self.busy:
            self.status.set("Waiting for the PBX result. The request will remain saved if delivery is unconfirmed.")
            return
        self.window.destroy()

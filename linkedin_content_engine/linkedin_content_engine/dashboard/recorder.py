"""Record-and-transcribe button: the browser records, Python transcribes.

The browser side uses MediaRecorder. `rx.call_script` awaits the Promise each script
returns and hands the result to a Python event: start() -> "ok" or an error code,
stop() -> the recording as a base64 data URL. The helper defines itself on first use
(window.__ceRec), so nothing has to be injected into the page head.

24 kbps keeps speech clear while staying under Reflex's 1 MB websocket message limit:
about 3 minutes of audio, which is also where recording auto-stops.
"""

import reflex as rx

from linkedin_content_engine.dashboard.state import DashboardState

_RECORDER_JS = """(window.__ceRec = window.__ceRec || (function () {
  let rec = null, chunks = [], stream = null, timer = null;
  const pick = () => ['audio/webm;codecs=opus', 'audio/webm', 'audio/mp4', 'audio/ogg;codecs=opus']
    .find(m => window.MediaRecorder && MediaRecorder.isTypeSupported(m)) || '';
  return {
    async start() {
      if (!window.isSecureContext || !navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) return 'insecure';
      if (!window.MediaRecorder) return 'unsupported';
      try { stream = await navigator.mediaDevices.getUserMedia({ audio: true }); } catch (e) { return 'denied'; }
      chunks = [];
      const mime = pick();
      rec = new MediaRecorder(stream, Object.assign({ audioBitsPerSecond: 24000 }, mime ? { mimeType: mime } : {}));
      rec.ondataavailable = e => { if (e.data && e.data.size) chunks.push(e.data); };
      rec.start();
      timer = setTimeout(() => { if (rec && rec.state === 'recording') rec.stop(); }, 180000);
      return 'ok';
    },
    stop() {
      return new Promise(resolve => {
        if (!rec) { resolve(''); return; }
        const finish = () => {
          clearTimeout(timer);
          if (stream) stream.getTracks().forEach(t => t.stop());
          const blob = new Blob(chunks, { type: rec.mimeType || 'audio/webm' });
          rec = null; stream = null;
          if (!blob.size) { resolve(''); return; }
          const reader = new FileReader();
          reader.onloadend = () => resolve(reader.result);
          reader.readAsDataURL(blob);
        };
        if (rec.state === 'inactive') finish(); else { rec.onstop = finish; rec.stop(); }
      });
    },
  };
})())"""

_START_JS = f"{_RECORDER_JS}.start()"
_STOP_JS = f"{_RECORDER_JS}.stop()"


def record_button(target: str, post_id=0) -> rx.Component:
    """Mic button for one text box. Click to start, click again to stop and transcribe.
    `target` is "weekly", "personal", "opinion" or "redraft"; `post_id` picks the Review card for
    "redraft" and the Your take topic for "opinion"."""
    is_recording = (DashboardState.recording_target == target) & (DashboardState.recording_post_id == post_id)
    is_transcribing = (DashboardState.transcribing_target == target) & (
        DashboardState.transcribing_post_id == post_id
    )
    return rx.cond(
        is_transcribing,
        rx.button(rx.spinner(size="1"), "Transcribing...", variant="outline", color_scheme="bronze", size="2", disabled=True),
        rx.cond(
            is_recording,
            rx.button(
                rx.icon("square", size=14),
                "Stop and transcribe",
                on_click=rx.call_script(_STOP_JS, callback=DashboardState.receive_recording),
                color_scheme="red",
                variant="solid",
                size="2",
            ),
            rx.button(
                rx.icon("mic", size=14),
                "Record",
                on_click=[
                    DashboardState.start_recording(target, post_id),
                    rx.call_script(_START_JS, callback=DashboardState.recording_started),
                ],
                color_scheme="bronze",
                variant="outline",
                size="2",
                disabled=DashboardState.recording_target != "",
            ),
        ),
    )

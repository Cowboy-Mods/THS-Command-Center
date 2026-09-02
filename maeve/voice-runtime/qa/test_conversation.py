"""Pure/static Stage 13 controlled-conversation QA; no network, browser, WSL, mic, or models."""
from __future__ import annotations
import ast
from pathlib import Path
import sys
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "broker"))
from conversation_policy import (ConversationSession, DEFAULT_GRACE_SECONDS, DEFAULT_NO_SPEECH_SECONDS,
    DEFAULT_SESSION_SECONDS, MAX_CONTEXT_CHARS, MAX_TURNS, MODEL, PERSONALITY_VERSION,
    SESSION_EXTENSION_SECONDS, SESSION_WARNING_55_PROMPT, SESSION_WARNING_59_PROMPT,
    STILL_THERE_PROMPT, TimeoutPolicy, build_prompt, classify_local_intent, validate_response)
sys.path.insert(0, str(ROOT / "worker"))
from reasoner_worker import describe_event, is_prohibited_event

SID, TOKEN, RID, RECORD = "a" * 32, "b" * 64, "c" * 32, "d" * 32

def rejected(callable_) -> None:
    try: callable_()
    except (RuntimeError, ValueError): pass
    else: raise AssertionError("fail-closed fixture was accepted")

def main() -> None:
    files = [ROOT / "broker" / "conversation_policy.py", ROOT / "broker" / "model_scheduler.py",
             ROOT / "worker" / "reasoner_worker.py", ROOT / "broker" / "server.py",
             ROOT / "worker" / "stt_worker.py", ROOT / "worker" / "qwen_worker.py"]
    for path in files: ast.parse(path.read_text(encoding="utf-8"))
    assert MODEL == "gpt-5.6-sol" and PERSONALITY_VERSION.endswith("v1")
    assert STILL_THERE_PROMPT == "Still with me, operator?"
    policy = TimeoutPolicy(); assert (policy.no_speech_seconds, policy.grace_seconds, policy.session_seconds) == (30, 15, 3600)
    assert (DEFAULT_NO_SPEECH_SECONDS, DEFAULT_GRACE_SECONDS, DEFAULT_SESSION_SECONDS, SESSION_EXTENSION_SECONDS) == (30, 15, 3600, 3600)
    assert "five minutes" in SESSION_WARNING_55_PROMPT and "one minute" in SESSION_WARNING_59_PROMPT
    rejected(lambda: TimeoutPolicy(no_speech_seconds=14)); rejected(lambda: TimeoutPolicy(grace_seconds=61)); rejected(lambda: TimeoutPolicy(session_seconds=3599)); rejected(lambda: TimeoutPolicy(session_seconds=3601))
    prompt = build_prompt("Confirm the harmless local test.", [])
    assert "Confirm the harmless local test." in prompt and "no tools" in prompt.casefold()
    assert validate_response("Maeve's restricted response is working.")
    for bad in ("```powershell", "<tool_call>", "Run cmd.exe now"): rejected(lambda bad=bad: validate_response(bad))
    for phrase in ("Maeve, end conversation.", "Maeve end the conversation", "Maeve, stop conversation"):
        assert classify_local_intent(phrase) == ("END", None)
    assert classify_local_intent("I'm thinking") == ("WAIT", 60)
    assert classify_local_intent("Maeve, give me a minute") == ("WAIT", 60)
    assert classify_local_intent("Give me 2 minutes") == ("WAIT", 120)
    assert classify_local_intent("Wait for 5 seconds") == ("WAIT", 15)
    assert classify_local_intent("Maeve, extend conversation") == ("EXTEND", 3600)
    assert classify_local_intent("Tell me what you are") == ("MESSAGE", None)

    session = ConversationSession(); assert session.state == "OFF"
    session.start(SID, TOKEN, record_id=RECORD); assert session.state == "READY" and session.context == [] and session.next_turn_id == 1
    assert not session.lease_expired(session.last_seen + 14) and session.lease_expired(session.last_seen + 16)
    assert not session.session_expired(session.started + 3599) and session.session_expired(session.started + 3600)
    assert session.next_session_warning(session.deadline-301) is None
    assert session.next_session_warning(session.deadline-300) == "FIVE_MINUTE_WARNING"
    assert session.next_session_warning(session.deadline-299) is None
    old_deadline=session.deadline; session.approve_extension(); assert session.deadline == old_deadline+3600 and session.extensions == 1
    assert session.next_session_warning(session.deadline-300) == "FIVE_MINUTE_WARNING"
    assert session.next_session_warning(session.deadline-60) == "FINAL_59_MINUTE_WARNING"
    rejected(lambda: session.claim_turn("d" * 32, TOKEN, 1)); rejected(lambda: session.claim_turn(SID, "e" * 64, 1))
    session.claim_turn(SID, TOKEN, 1); assert session.pending_turn_id == 1 and session.state == "PROCESSING_STT"
    rejected(lambda: session.claim_turn(SID, TOKEN, 1)); rejected(lambda: session.claim_turn(SID, TOKEN, 2))
    session.add_turn("Hello Maeve", "Hello, operator."); session.bind_response(1, RID)
    rejected(lambda: session.complete_playback(SID, TOKEN, 2, RID)); rejected(lambda: session.complete_playback(SID, TOKEN, 1, "d" * 32))
    session.complete_playback(SID, TOKEN, 1, RID); assert session.next_turn_id == 2 and session.state == "AUTO_CONTINUE"
    # One explicit start supports multiple sequential accepted turns; each turn advances once.
    session.claim_turn(SID, TOKEN, 2); session.add_turn("Second turn", "Second answer."); session.bind_response(2, "e" * 32)
    session.complete_playback(SID, TOKEN, 2, "e" * 32); assert session.next_turn_id == 3 and session.turns == 2 and session.state == "AUTO_CONTINUE"
    session.mute(); assert session.muted and session.state == "MUTED"
    session.unmute(); assert not session.muted and session.state == "READY" and session.next_turn_id == 3
    deadline_before_wait=session.deadline; session.claim_turn(SID, TOKEN, 3); session.complete_control_turn(60); assert session.muted and session.next_turn_id == 4 and session.deadline == deadline_before_wait
    with patch("conversation_policy.time.monotonic", return_value=session.wait_until - 1): rejected(session.unmute)
    with patch("conversation_policy.time.monotonic", return_value=session.wait_until + 1): session.unmute()
    session.end(); assert session.state == "OFF" and session.context == [] and session.session_token is None

    retained = ConversationSession(); retained.start(SID, TOKEN, record_id=RECORD); retained.claim_turn(SID, TOKEN, 1)
    retained.add_turn("Status", "Ready, operator."); retained.bind_response(1, RID); retained.complete_playback(SID, TOKEN, 1, RID)
    resume_id = retained.end(retain=True, resume_id=RECORD); assert resume_id == RECORD and retained.context == []
    rejected(lambda: retained.start("1" * 32, "2" * 64, resume_id))
    retained.start("1" * 32, "2" * 64, resume_id, resume_confirmed=True); assert retained.context and retained.turns == 1 and retained.state == "MUTED" and retained.muted
    retained.end(); assert retained.resumable_context == []
    empty_resume=ConversationSession(); empty_resume.start(SID,TOKEN,record_id="3"*32); empty_id=empty_resume.end(retain=True,resume_id="3"*32)
    empty_resume.start("4"*32,"5"*64,empty_id,resume_confirmed=True); assert empty_resume.context == [] and empty_resume.state == "MUTED"; empty_resume.end()
    spoken_end=ConversationSession(); spoken_end.start(SID,TOKEN,record_id=RECORD); spoken_end.claim_turn(SID,TOKEN,1)
    spoken_end_id=spoken_end.end(retain=True,resume_id=RECORD)
    assert spoken_end_id == RECORD and spoken_end.resumable_id == RECORD and spoken_end.resumable_context == []
    assert spoken_end.state == "OFF" and spoken_end.session_id is None and spoken_end.session_token is None and spoken_end.pending_turn_id is None
    rejected(lambda: spoken_end.start("6"*32,"7"*64,spoken_end_id,resume_confirmed=False))
    rejected(lambda: spoken_end.start("6"*32,"7"*64,"8"*32,resume_confirmed=True))
    spoken_end.start("6"*32,"7"*64,spoken_end_id,resume_confirmed=True); assert spoken_end.state == "MUTED" and spoken_end.muted and spoken_end.session_token == "7"*64
    spoken_end.end(); assert spoken_end.resumable_id is None and spoken_end.resumable_context == []
    with patch("conversation_policy.time.monotonic", side_effect=[0, 3600]):
        expired=ConversationSession(); expired.start(SID, TOKEN, record_id=RECORD); rejected(expired.require_active)
    capped=ConversationSession(); capped.start(SID, TOKEN, record_id=RECORD); capped.turns=MAX_TURNS; rejected(capped.require_active)
    assert MAX_CONTEXT_CHARS == 12000

    reasoner=(ROOT / "worker" / "reasoner_worker.py").read_text(encoding="utf-8")
    assert all(flag in reasoner for flag in ("--ephemeral", "--ignore-user-config", "--ignore-rules", "--sandbox", "read-only"))
    assert all(name in reasoner for name in ("shell_tool", "browser_use", "computer_use", "plugins", "multi_agent", "unified_exec", "view_image", "standalone_web_search"))
    fixtures=(({"type":"thread.started"},"lifecycle",False),({"type":"item.completed","item":{"type":"agent_message","text":"redacted"}},"assistant-text",False),({"type":"item.completed","item":{"type":"command_execution"}},"genuine-tool-or-action",True),({"type":"item.completed","item":{"type":"unknown_status"}},"unknown",True))
    for event,classification,prohibited in fixtures:
        descriptor=describe_event(event); assert descriptor["classification"]==classification and is_prohibited_event(event) is prohibited and "redacted" not in str(descriptor)
    for forbidden in ("auth.json", "OPENAI_API_KEY", "api.openai.com", "requests.", "urllib"): assert forbidden not in reasoner

    controller=(ROOT / "ui" / "scripts" / "conversation-controller.js").read_text(encoding="utf-8")
    runtime=(ROOT / "ui" / "scripts" / "runtime.js").read_text(encoding="utf-8")
    server=(ROOT / "broker" / "server.py").read_text(encoding="utf-8")
    html=(ROOT / "ui" / "index.html").read_text(encoding="utf-8")
    assert controller.count("getUserMedia(") == 1 and "captureOwned=true" in controller and "Only one conversation capture may exist" in controller
    assert controller.index("starting=true") < controller.index('apiFetch("/api/conversation/start"')
    assert all(value in controller for value in ("captureEpoch", "sessionId", "sessionToken", "nextTurn", "cleanupPromise", "X-Maeve-Conversation-Turn"))
    categories=("STT_START_FAILED","STT_TIMEOUT","STT_WORKER_FAILED","STT_PROTOCOL_FAILED","STT_EVIDENCE_FAILED","STT_EMPTY_TRANSCRIPT","STT_FAILED","INTENT_FAILED","REASONER_START_FAILED","REASONER_RESPONSE_FAILED","RESPONSE_IDENTITY_FAILED","VOICE_GENERATION_FAILED","QWEN_START_FAILED","QWEN_TIMEOUT","QWEN_WORKER_FAILED","QWEN_PROTOCOL_MISSING","QWEN_PROTOCOL_INVALID_JSON","QWEN_PROTOCOL_NON_OBJECT","QWEN_PROTOCOL_SCHEMA_FAILED","QWEN_PROTOCOL_FAILED","QWEN_EVIDENCE_FAILED","QWEN_AUDIO_FAILED","QWEN_FAILED","PLAYBACK_PREP_FAILED")
    assert all(category in server and category in controller for category in categories)
    assert all(category.replace("_FAILED", "") not in {"audio", "transcript", "response", "prompt", "token", "credential", "environment", "command"} for category in categories)
    assert 'GENERIC_TURN_FAILURE = "TURN_FAILED"' in server and '"failureCategory":category' in server
    failure_helper=server.split("def turn_failure_payload",1)[1].split("class VoiceWorker",1)[0]
    assert all(value not in failure_helper.casefold() for value in ("audio", "transcript", "prompt", "token", "credential", "environment", "command", "str(error)", "repr(error)"))
    assert 'data.failureCategory' in controller and '"TURN_FAILED"' in controller and "NO AUTOMATIC RETRY" in controller
    assert all(value in controller for value in ("SILENCE_PROMPT_MS=30000", "SILENCE_GRACE_MS=15000", "session:[3600000,3600000]", "Still with me, operator?", "timeoutPolicy", "resumeId", "resumeConfirmed"))
    assert all(value in controller for value in ("/api/conversation/cancel", "/api/conversation/timeout", "/api/conversation/heartbeat", "heartbeatTimer", "keepalive:true", "cancelConversationPlayback"))
    assert "localStorage" not in controller and "sessionStorage" not in controller and "indexedDB" not in controller
    assert "RELISTEN_PAUSE_MS=650" in controller and "RELISTEN_PAUSE_MS" in controller.split("constants:Object.freeze",1)[1]
    assert controller.count('await scheduleRelisten("normal")') == 2 and controller.count('await scheduleRelisten("grace")') == 1
    relisten_block=controller.split('function scheduleRelisten',1)[1].split('async function finishTurn',1)[0]
    assert all(value in relisten_block for value in ('cancelRelisten()', 'config.playbackActive()', 'const epoch=captureEpoch', 'epoch!==captureEpoch', '!active', 'muted', 'setTimeout', 'RELISTEN_PAUSE_MS', 'await startListening(mode)'))
    assert 'PLAYBACK ENDED · MICROPHONE CLOSED · LISTENING RESUMES IN' in relisten_block
    assert controller.index('state("LISTENING"') < controller.index('navigator.mediaDevices.getUserMedia')
    assert all(value not in controller for value in ("createOscillator", "OscillatorNode", "relisten-beep", "relisten-tone"))
    discard_block=controller.split("function discardCapture",1)[1].split("function resetButtons",1)[0]
    assert "cancelRelisten()" in discard_block and "captureEpoch+=1" in discard_block
    finalize_block=controller.split("function finalizeLocal",1)[1].split("function cleanup",1)[0]
    assert "discardCapture()" in finalize_block and "sessionId=null" in finalize_block and "sessionToken=null" in finalize_block
    assert 'id="conversation-cancel"' in html and runtime.count('"conversation-response"') >= 4
    assert 'playResponse:data=>playValidatedAudio(data.audioUrl,data.audio,"conversation-response",data.responseId)' in runtime
    assert 'playValidatedAudio(result.audioUrl,result.audio,"stage13-response",responseId)' in runtime
    turn_block=server.split('if path == "/api/conversation/turn":',1)[1].split('body = self._read_json_body()',1)[0]
    qwen_block=server.split("class VoiceWorker",1)[1].split("VOICE = VoiceWorker()",1)[0]
    assert turn_block.index("CONVERSATION.claim_turn") < turn_block.index("STT.transcribe") < turn_block.index("classify_local_intent") < turn_block.index("REASONER.reason")
    assert all(value in turn_block for value in ('intent == "END"', 'intent == "WAIT"', "cleanup_conversation", "response_id"))
    assert all(f'TurnStageFailure("{category}")' in turn_block or category in server.split("class SttService",1)[1].split("class MaeveHandler",1)[0] or category in qwen_block for category in categories)
    stt_block=server.split("def transcribe(self, audio",1)[1].split("def consume_approval",1)[0]
    stt_service_block=server.split("class SttService",1)[1].split("STT = SttService()",1)[0]
    reason_block=server.split("def reason(self, transcript",1)[1].split("def cancel(self)",1)[0]
    assert stt_block.count('TurnStageFailure("STT_START_FAILED")') >= 2 and 'TurnStageFailure("STT_FAILED")' in stt_block
    assert all(f'TurnStageFailure("{category}")' in stt_service_block for category in ("STT_TIMEOUT","STT_WORKER_FAILED","STT_PROTOCOL_FAILED","STT_EVIDENCE_FAILED","STT_EMPTY_TRANSCRIPT"))
    assert all(category in qwen_block for category in ("QWEN_START_FAILED","QWEN_TIMEOUT","QWEN_WORKER_FAILED","QWEN_PROTOCOL_MISSING","QWEN_PROTOCOL_INVALID_JSON","QWEN_PROTOCOL_NON_OBJECT","QWEN_PROTOCOL_SCHEMA_FAILED","QWEN_PROTOCOL_FAILED","QWEN_EVIDENCE_FAILED","QWEN_AUDIO_FAILED","QWEN_FAILED"))
    assert 'except OSError: raise TurnStageFailure("REASONER_START_FAILED")' in reason_block and reason_block.count('TurnStageFailure("REASONER_RESPONSE_FAILED")') >= 3
    assert 'except Exception as error:' in turn_block and 'cleanup_conversation(retain=False, stop_worker=True)' in turn_block and 'turn_failure_payload(error)' in turn_block
    assert turn_block.count('REASONER.reason(transcript, context)') == 1 and turn_block.count('VOICE.generate_response(response_text') == 1
    assert 'response_limit=16,' in turn_block and 'require_stt=False' in turn_block
    assert 'except ProviderFailure: raise TurnStageFailure("VOICE_GENERATION_FAILED")' in turn_block
    assert '"qwenStartCount": self.qwen_start_count' in server and '"qwenReadyRequired": self.selected_provider == "QWEN"' in server
    assert turn_block.index('response_id = secrets.token_hex(16)') < turn_block.index('VOICE.generate_response(response_text') < turn_block.index('response = {"status": "READY_FOR_PLAYBACK"')
    end_block=turn_block.split('if intent == "END":',1)[1].split('if intent == "WAIT":',1)[0]
    assert 'cleanup_conversation(retain=True, stop_worker=True)' in end_block and 'cleanup_conversation(retain=False' not in end_block
    assert all(value in end_block for value in ('"resumable":True', '"resumeId":resume_id', '"stoppingTurn":turn_id', '"microphone":"CLOSED"', '"sessionTokenCleared":CONVERSATION.session_token is None', '"openAIRequestCreated":False'))
    assert "REASONER.reason" not in end_block
    ended_client=controller.split('if(data.status==="ENDED")',1)[1].split('if(data.status==="PAUSED")',1)[0]
    assert all(value in ended_client for value in ('data.resumeId!==conversationId', 'data.stoppingTurn!==submittedTurn', 'data.openAIRequestCreated!==false', 'resumeId=data.resumeId', 'RESUMABLE CONTEXT RETAINED', 'finalizeLocal("OFF"'))
    cancel_client=controller.split('function cancelSession',1)[1].split('function fail',1)[0]
    assert 'cleanup("cancel"' in cancel_client and 'false' in cancel_client and 'CONTEXT CLEARED' in cancel_client
    assert 'cleanup("timeout","SESSION TIMEOUT · RESUMABLE CONTEXT RETAINED · MICROPHONE CLOSED",true)' in controller
    assert all(value in server for value in ("CONVERSATION_TOKEN_HEADER", "/api/conversation/playback-complete", "/api/conversation/silence-prompt", "/api/conversation/session-warning", "/api/conversation/cancel", "/api/conversation/timeout", "/api/conversation/heartbeat", "conversation_watchdog"))
    assert all(value in controller for value in ("FIVE_MINUTE_WARNING", "FINAL_59_MINUTE_WARNING", "trusted-physical-resume", "RESUME CONVERSATION", "scheduleSessionTimeout"))
    assert "turnInFlight=true" in controller and "turnInFlight=false;aborter=null" in controller
    automatic_mute=controller.split("async function setMuted",1)[1].split("function toggleMute",1)[0]
    assert "automatic=false" in automatic_mute and "if(!automatic){aborter?.abort();config.cancelConversationPlayback();}" in automatic_mute
    assert 'automatic&&turnInFlight?"MIC CLOSED · SUBMITTED TURN CONTINUES · DELIBERATE UNMUTE REQUIRED"' in automatic_mute
    assert 'setMuted(true,true).catch(fail)' in controller and controller.count('setMuted(true,true).catch(fail)') == 2
    assert 'state(muted?"MUTED":"AUTO_CONTINUE"' in controller and "DELIBERATE UNMUTE REQUIRED" in controller
    assert 'if(active&&!muted)await scheduleRelisten("normal")' in controller
    assert 'function cancelSession(){return cleanup("cancel"' in controller and 'window.addEventListener("pagehide",()=>{if(active)cleanup("end"' in controller
    assert controller.count('conversationFetch("/api/conversation/turn"') == 1
    turn_client=controller.split('conversationFetch("/api/conversation/turn"',1)[1].split("async function",1)[0]
    assert "NO AUTOMATIC RETRY" in turn_client
    assert "VOICE_GENERATION_FAILED" in turn_client
    assert 'config.voiceProviderLabel()' in controller and "LOCAL CANDIDATE B" not in controller
    assert all(value in server for value in ("REASONER.cancel()", "self.active_process", "process.terminate()", "process.kill()", "require_stt=False"))
    cleanup_block=server.split("def cleanup_conversation",1)[1].split("def conversation_watchdog",1)[0]
    assert all(value not in cleanup_block.casefold() for value in ("taskkill", "maeve_console", "farm_manager", "agent", "codex.exe"))
    assert 'if(!muted)await startListening("normal")' in controller
    assert server.count('if path == "/api/response/playback-complete"') == 1 and 'body.get("responseId")' in server
    assert turn_block.count('REASONER.reason(transcript, context)') == 1 and turn_block.count('VOICE.generate_response(response_text') == 1
    assert 'require_stt=False' in turn_block and 'self.selected_provider == "QWEN"' in qwen_block
    review_block=server.split('if path == "/api/response/approve":',1)[1].split('if path == "/api/response/discard":',1)[0]
    assert 'STT.consume_approval' in review_block and 'require_stt=False' in review_block and 'CONVERSATION' not in review_block
    print("STAGE13_CONTINUOUS_SESSION_STATIC_AND_UNIT_QA=PASS assertions=218 network=0 browser=0 wsl=0 microphone=0 models=0")

if __name__ == "__main__": main()

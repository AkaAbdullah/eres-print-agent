from eres_print_agent.state_machine import PrintJobStatus, is_legal_transition, is_terminal


def test_queued_can_move_to_received_or_cancelled():
    assert is_legal_transition(PrintJobStatus.QUEUED, PrintJobStatus.RECEIVED)
    assert is_legal_transition(PrintJobStatus.QUEUED, PrintJobStatus.CANCELLED)
    assert not is_legal_transition(PrintJobStatus.QUEUED, PrintJobStatus.PRINTING)
    assert not is_legal_transition(PrintJobStatus.QUEUED, PrintJobStatus.COMPLETED)


def test_printing_can_only_reach_completed_or_failed():
    assert is_legal_transition(PrintJobStatus.PRINTING, PrintJobStatus.COMPLETED)
    assert is_legal_transition(PrintJobStatus.PRINTING, PrintJobStatus.FAILED)
    assert not is_legal_transition(PrintJobStatus.PRINTING, PrintJobStatus.CANCELLED)
    assert not is_legal_transition(PrintJobStatus.PRINTING, PrintJobStatus.RECEIVED)


def test_terminal_statuses_accept_no_further_transitions():
    for status in (PrintJobStatus.COMPLETED, PrintJobStatus.FAILED, PrintJobStatus.CANCELLED):
        assert is_terminal(status)
        assert not is_legal_transition(status, PrintJobStatus.RECEIVED)
        assert not is_legal_transition(status, PrintJobStatus.PRINTING)


def test_same_status_is_always_a_legal_idempotent_transition():
    for status in PrintJobStatus:
        assert is_legal_transition(status, status)


def test_waiting_for_printer_can_resume_to_printing():
    assert is_legal_transition(PrintJobStatus.WAITING_FOR_PRINTER, PrintJobStatus.PRINTING)
    assert is_legal_transition(PrintJobStatus.WAITING_FOR_PRINTER, PrintJobStatus.FAILED)
    assert is_legal_transition(PrintJobStatus.WAITING_FOR_PRINTER, PrintJobStatus.CANCELLED)

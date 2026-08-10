from knowledgenexus.foundation.cli.confluence_subtree_corpus import main


def test_help_exits_zero_without_failure_payload(capsys):
    assert main(["--help"]) == 0
    assert '"status":"failed"' not in capsys.readouterr().out


def test_drawio_phase_fails_closed_without_production_adapters(capsys, tmp_path):
    result = main(["capture-drawio", "--state-dir", str(tmp_path), "--max-pages", "5000"])
    assert result == 2
    assert capsys.readouterr().out == '{"status":"failed","error":"configuration"}\n'

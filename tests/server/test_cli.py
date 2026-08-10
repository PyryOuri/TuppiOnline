from tuppi_server.app import _argument_parser, _port_value


def test_server_cli_defaults_to_localhost_and_known_port(monkeypatch) -> None:
    monkeypatch.delenv("TUPPI_SERVER_HOST", raising=False)
    monkeypatch.delenv("TUPPI_SERVER_PORT", raising=False)

    args = _argument_parser().parse_args([])

    assert args.host == "127.0.0.1"
    assert args.port == 8765
    assert args.lan is False
    assert args.check is False


def test_server_cli_lan_mode_selects_all_interfaces() -> None:
    args = _argument_parser().parse_args(["--lan", "--port", "9876"])

    assert args.lan is True
    assert args.port == 9876


def test_server_cli_rejects_invalid_ports() -> None:
    for raw in ("0", "65536", "not-a-port"):
        try:
            _port_value(raw)
        except Exception:
            continue
        raise AssertionError(f"port {raw!r} should be rejected")

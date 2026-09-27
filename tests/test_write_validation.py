"""The write path rejects pages that are not worth keeping.

This is the load-bearing idea of the skill, so it is tested at the CLI boundary
— the exit code is the contract an agent actually meets, not an internal call.

Motivation is measured, not aesthetic: in the corpus this was designed against,
104 of 495 pages were auto-generated stubs averaging 277 bytes, and they took
the top two result slots for real queries. A page nobody can trace to a file,
or one too thin to say anything the source does not, costs more than it returns.
"""
import pytest

from pagelore import write as memory_write

LONG = ("The reap loop waits on the child before closing the master fd, so a child "
        "that ignores SIGTERM keeps the fd open and waitpid never returns. " * 3)


@pytest.fixture()
def repo(tmp_path):
    """A project root with a real file to cite and an empty store beside it."""
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "real.ts").write_text("export {}")
    (tmp_path / ".memory").mkdir()
    return tmp_path


def run(repo, *args, body=LONG):
    argv = ["--store", str(repo / ".memory")]
    if body is not None:
        argv += ["--body", body]
    return memory_write.main([*argv, *args])


def ok_args(slug="pty-hangs-on-exit"):
    return ["--slug", slug, "--title", "PTY hangs on exit", "--kind", "bug",
            "--source", "src/real.ts"]


def test_accepts_a_well_formed_page(repo):
    assert run(repo, *ok_args()) == 0
    assert (repo / ".memory" / "pty-hangs-on-exit.md").is_file()


def test_rejects_missing_sources(repo, capsys):
    rc = run(repo, "--slug", "no-sources", "--title", "T", "--kind", "bug")
    assert rc == 1
    err = capsys.readouterr().err
    assert "source" in err.lower()
    assert "FIX:" in err


def test_rejects_source_that_does_not_exist(repo, capsys):
    rc = run(repo, "--slug", "bad-source", "--title", "T", "--kind", "bug",
             "--source", "src/imaginary.ts")
    assert rc == 1
    assert "imaginary" in capsys.readouterr().err


def test_rejects_body_too_short_to_be_worth_keeping(repo, capsys):
    rc = run(repo, *ok_args(), body="Uses a mutex.")
    assert rc == 1
    err = capsys.readouterr().err
    assert str(memory_write.MIN_BODY) in err
    assert "FIX:" in err


def test_rejects_unknown_kind(repo, capsys):
    rc = run(repo, "--slug", "odd-kind", "--title", "T", "--kind", "rationale",
             "--source", "src/real.ts")
    assert rc == 1
    assert "kind" in capsys.readouterr().err.lower()


def test_requires_an_explicit_body(repo, capsys):
    """The old default wrote `## Context / TODO: why this matters.` — a stub
    generator with a friendly face."""
    rc = run(repo, *ok_args(), body=None)
    assert rc == 1
    assert "FIX:" in capsys.readouterr().err


def test_a_rejected_write_creates_no_file(repo):
    run(repo, "--slug", "never-written", "--title", "T", "--kind", "bug")
    assert not (repo / ".memory" / "never-written.md").exists()


def test_source_may_be_given_relative_to_the_store_parent(repo):
    """Agents cite paths from the repo root; the CLI may be run from elsewhere."""
    assert run(repo, *ok_args("root-relative")) == 0


def test_a_missing_kind_is_countable_apart_from_a_wrong_one(repo):
    """Both were logged as `bad_kind`, so the per-code counts could not tell "the
    agent forgot the flag" from "the agent picked a kind we do not have" — two
    problems whose fixes point in opposite directions."""
    import json

    from pagelore import lib as memory_lib
    run(repo, "--slug", "a", "--title", "T", "--source", "src/real.ts")
    run(repo, "--slug", "b", "--title", "T", "--kind", "rationale", "--source", "src/real.ts")
    codes = [json.loads(line)["code"]
             for line in (repo / ".memory" / memory_lib.LOG_NAME)
             .read_text(encoding="utf-8").splitlines()
             if json.loads(line)["event"] == "reject"]
    assert codes == ["no_kind", "bad_kind"]


def test_the_documented_kinds_are_exactly_the_accepted_ones(repo):
    """`references/page-format.md` and the shipped page template both advertised
    `kind: note`, which the gate rejects, and neither mentioned `howto`."""
    from pathlib import Path
    root = Path(__file__).resolve().parents[1]
    reference = (root / "docs" / "page-format.md").read_text(encoding="utf-8")
    template = (root / "src" / "pagelore" / "data"
                / "page-template.md").read_text(encoding="utf-8")
    for kind in memory_write.KINDS:
        assert f"`{kind}`" in reference, f"{kind} is accepted but not documented"
    assert "note" not in reference.replace("Notes", "").replace("note that", "")
    assert f"kind: {memory_write.KINDS[0]}" in template


SECRET_SAMPLES = [
    ("aws_access_key", "AKIA1234567890ABCDEF"),
    ("github_token", "ghp_" + "a" * 36),
    ("github_fine_grained_pat", "github_pat_" + "a" * 40),
    ("anthropic_api_key", "sk-ant-" + "a" * 40),
    ("openai_api_key", "sk-" + "a" * 40),
    ("slack_token", "xoxb-" + "1234567890-1234567890abcdefghij"),
    ("private_key_pem", "-----BEGIN RSA PRIVATE KEY-----"),
]

# Reads as random (entropy >= 4.5 bits/char): a plausible pasted credential.
HIGH_ENTROPY = "Zk3x9QpL2vB8mR7tN0yC5wJ1hU4sD6eA9gT3iX7oV2z"
# A real SHA-1: entropy tops out at log2(16) = 4.0 bits/char over a 16-symbol
# hex alphabet, so it must never warn.
SHA1_LIKE = "1234567890abcdef1234567890abcdef12345678"
# A long identifier in the style this codebase actually uses: skewed letter
# frequencies keep its entropy well under the threshold.
SNAKE_CASE = "the_reap_loop_waits_on_the_child_before_closing_the_master_fd_handle"


@pytest.mark.parametrize("kind,secret", SECRET_SAMPLES)
def test_rejects_a_body_containing_a_credential(repo, capsys, kind, secret):
    slug = "secret-" + kind.replace("_", "-")
    body = LONG + "\n" + secret
    rc = run(repo, *ok_args(slug), body=body)
    assert rc == 1
    err = capsys.readouterr().err
    assert "FIX:" in err
    assert secret not in err
    assert kind in err
    assert not (repo / ".memory" / f"{slug}.md").exists()


def test_a_credential_in_the_title_is_also_refused(repo, capsys):
    secret = "AKIA1234567890ABCDEF"
    rc = run(repo, "--slug", "secret-title", "--title", f"Key {secret} leaked",
             "--kind", "bug", "--source", "src/real.ts", body=LONG)
    assert rc == 1
    err = capsys.readouterr().err
    assert secret not in err
    # Named as "title", never folded into the body's own line numbering.
    assert "title" in err
    assert "body line" not in err


def test_the_reported_line_counts_only_the_body_text_the_agent_typed(repo, capsys):
    """The gate used to scan "title\\n" + body as one string, so a secret on
    the body's own first line was reported as line 2 — off by one from what
    `--body` actually contains."""
    secret = "AKIA1234567890ABCDEF"
    body = "First body line, unrelated filler text here.\n" + secret
    rc = run(repo, "--slug", "line-count", "--title", "A distinct title", "--kind", "bug",
             "--source", "src/real.ts", body=body)
    assert rc == 1
    err = capsys.readouterr().err
    assert "body line 2" in err
    assert "body line 3" not in err


def test_the_matched_secret_never_reaches_stderr_or_the_log(repo, capsys):
    from pagelore import lib as memory_lib

    secret = "AKIA1234567890ABCDEF"
    body = LONG + "\n" + secret
    rc = run(repo, *ok_args("secret-not-logged"), body=body)
    assert rc == 1
    assert secret not in capsys.readouterr().err
    log_text = (repo / ".memory" / memory_lib.LOG_NAME).read_text(encoding="utf-8")
    assert secret not in log_text


# Ordinary kebab-case prose and wiki-links whose tail happens to spell a
# pattern's prefix mid-word (e.g. "risk-" contains "sk-", "disk-" contains
# "sk-", "brisk-" contains "sk-") must never be refused. Every one of these
# writes cleanly on `main`'s predecessor with no secrets check at all.
MID_WORD_FALSE_POSITIVES = [
    "See [[task-queue-drains-before-shutdown-on-sigterm]] and "
    "risk-assessment-of-the-renderer-pipeline for background.",
    "A disk-image-based-backup-strategy-for-production-servers was chosen.",
    "brisk-walking-is-recommended-for-cardiovascular-health-improvement, per the study.",
    "The task-scheduler-retry-backoff-policy-for-flaky-network-calls was updated.",
    "A desk-lamp-motion-sensor-firmware-update-rollout-plan-for-the-office was filed.",
    "The mask-detection-model-training-pipeline-configuration-notes are attached.",
]


@pytest.mark.parametrize("prose", MID_WORD_FALSE_POSITIVES)
def test_ordinary_kebab_case_prose_is_not_refused(repo, capsys, prose):
    body = LONG + "\n" + prose
    rc = run(repo, *ok_args("kebab-prose"), body=body)
    err = capsys.readouterr().err
    assert rc == 0, err
    assert "REJECTED" not in err


def test_a_github_token_prefix_mid_identifier_is_not_refused(repo, capsys):
    """"...ghs_" spelled inside a longer identifier, not as its own token."""
    body = LONG + "\nThe variable is called somethingghs_" + "a" * 36 + "_config_value."
    rc = run(repo, *ok_args("ghs-mid-word"), body=body)
    err = capsys.readouterr().err
    assert rc == 0, err


def test_an_aws_prefix_mid_identifier_is_not_refused(repo, capsys):
    """"...AKIA..." spelled inside a longer identifier, not as its own token."""
    body = LONG + "\nSee the backup-service PANCAKIA1234567890ABCDEF-name for details."
    rc = run(repo, *ok_args("akia-mid-word"), body=body)
    err = capsys.readouterr().err
    assert rc == 0, err


@pytest.mark.parametrize("prefix", ["", " ", "=", '"', ":"])
def test_a_real_credential_is_still_caught_after_common_punctuation(repo, capsys, prefix):
    """The boundary fix must not eat the positive cases: a key at the start of
    a line, or right after a space/=/quote/colon, still refuses the write."""
    secret = "AKIA1234567890ABCDEF"
    body = LONG + "\n" + prefix + secret
    slug = "akia-after-" + (
        {"": "nothing", " ": "space", "=": "equals", '"': "quote", ":": "colon"}[prefix])
    rc = run(repo, *ok_args(slug), body=body)
    assert rc == 1
    assert secret not in capsys.readouterr().err


def test_an_anthropic_key_is_not_also_reported_as_an_openai_key(repo, capsys):
    """sk-ant-... starts with the same `sk-` prefix as an OpenAI key; it must
    produce one finding, not two."""
    from pagelore import write as memory_write

    secret = "sk-ant-" + "a" * 40
    kinds = [kind for kind, _ in memory_write.find_secrets(secret)]
    assert kinds == ["anthropic_api_key"]


def test_high_entropy_string_warns_but_the_page_is_still_written(repo, capsys):
    body = LONG + "\n" + HIGH_ENTROPY
    rc = run(repo, *ok_args("entropy-page"), body=body)
    assert rc == 0
    err = capsys.readouterr().err
    assert "⚠" in err
    assert "looks like a credential (high-entropy string)" in err
    assert (repo / ".memory" / "entropy-page.md").is_file()


def test_the_entropy_warning_counts_only_the_body_text_the_agent_typed(repo, capsys):
    body = "First body line, unrelated filler text here.\n" + HIGH_ENTROPY + "\n" + LONG
    rc = run(repo, *ok_args("entropy-line-count"), body=body)
    assert rc == 0
    err = capsys.readouterr().err
    assert "⚠ body line 2 looks like a credential" in err


def test_a_high_entropy_title_is_reported_as_title_not_a_line(repo, capsys):
    rc = run(repo, "--slug", "entropy-title", "--title", HIGH_ENTROPY, "--kind", "bug",
             "--source", "src/real.ts", body=LONG)
    assert rc == 0
    err = capsys.readouterr().err
    assert "⚠ title looks like a credential" in err


def test_a_sha1_style_hex_string_does_not_warn(repo, capsys):
    body = LONG + "\n" + SHA1_LIKE
    rc = run(repo, *ok_args("sha-page"), body=body)
    assert rc == 0
    assert "⚠" not in capsys.readouterr().err


def test_a_long_snake_case_identifier_does_not_warn(repo, capsys):
    body = LONG + "\n" + SNAKE_CASE
    rc = run(repo, *ok_args("snake-page"), body=body)
    assert rc == 0
    assert "⚠" not in capsys.readouterr().err


def test_every_rejection_names_the_next_command(repo, capsys):
    """A rejection that does not say what to do next just teaches the agent to
    stop writing."""
    for args, body in [
        (["--slug", "a", "--title", "T", "--kind", "bug"], LONG),
        (ok_args("b"), "short"),
        (["--slug", "c", "--title", "T", "--kind", "nope", "--source", "src/real.ts"], LONG),
    ]:
        capsys.readouterr()
        assert run(repo, *args, body=body) == 1
        err = capsys.readouterr().err
        assert err.startswith("REJECTED:")
        assert "FIX:" in err

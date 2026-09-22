"""Live terminal demo of the VersyTalks grader.

Run:  uv run python experiments/demo.py
"""

import json
from pathlib import Path

from rich.console import Console
from rich.panel import Panel
from rich.prompt import Confirm, Prompt
from rich.rule import Rule
from rich.table import Table
from rich.text import Text

from versytalks_grader.grader import grade

console = Console()

SAMPLES = json.loads(Path("experiments/samples.json").read_text())

DIMS = [
    ("point", "Point", "What are you asking us to accept?"),
    ("mechanism", "Mechanism", "Why is it true?"),
    ("evidence", "Evidence", "What supports it?"),
    ("impact", "Impact", "Why does it matter, and to whom?"),
]

BANDS = [("Foundations", "4-6"), ("Developing", "7-8"), ("Solid", "9-10"), ("Strong", "11-20")]

FLAG_NAMES = {
    "no_position": "No position taken",
    "assertion_only": "Asserted, not explained",
    "name_drop_evidence": "Source named, not explained",
    "thin_submission": "Short submission",
    "too_short": "Too short to grade",
    "clustered_arguments": "Too many claims at once",
    "rhetoric_without_work": "Rhetoric doing no work",
    "off_topic": "Off topic",
    "wrong_side": "Wrong side",
}


def read_argument():
    console.print("\n[bold]Paste the argument.[/] When done, type [bold cyan]END[/] on its own line and press Enter.\n")
    lines = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line.strip() == "END":
            break
        lines.append(line)
    return "\n".join(lines).strip()


def choose_input():
    console.print(Rule("[bold]VersyTalks · AI Debate Grading (Beta)[/]"))
    console.print("  [bold]1[/]  Lecture attendance   [dim](real submission)[/]")
    console.print("  [bold]2[/]  Right to privacy     [dim](real submission)[/]")
    console.print("  [bold]3[/]  Parenting tests      [dim](real submission)[/]")
    console.print("  [bold]4[/]  Paste your own argument")
    choice = Prompt.ask("\nChoose", choices=["1", "2", "3", "4"], default="4")

    if choice in ("1", "2", "3"):
        sample = {"1": "S3", "2": "S2", "3": "S1"}[choice]
        s = next(x for x in SAMPLES if x["id"] == sample)
        return s["text"], s.get("motion"), None

    motion = Prompt.ask("Motion [dim](Enter to skip)[/]", default="").strip() or None
    side = Prompt.ask("Side", choices=["For", "Against", "skip"], default="skip")
    side = None if side == "skip" else side
    return read_argument(), motion, side


def score_bar(n):
    return Text("■" * n, style="bold green") + Text("□" * (5 - n), style="dim")


def show_submission(text, motion):
    header = f"[italic]{motion}[/]" if motion else "[dim]No motion given[/]"
    console.print(Panel(text, title=header, title_align="left",
                        subtitle=f"{len(text.split())} words", border_style="dim"))


def show_result(result, meta, show_coach):
    if not result["sufficient"]:
        console.print(Panel(result["insufficient_reason"], title="[bold]Not graded[/]",
                            border_style="yellow"))
        return

    label, total = result["label"], result["total"]
    bands = Text("  ")
    for name, rng in BANDS:
        style = "bold black on green" if name == label else "dim"
        bands.append(f" {name} {rng} ", style=style)
        bands.append("  ")

    console.print(Panel(
        Text.assemble((f"{label}", "bold green"), ("   ", ""), (f"{total} / 20", "bold")),
        title="Level", title_align="left", border_style="green", subtitle=bands, subtitle_align="left",
    ))

    table = Table(show_header=False, box=None, padding=(0, 2))
    for key, name, question in DIMS:
        s = result["scores"][key]
        table.add_row(Text(name, style="bold"), score_bar(s), Text(f"{s}/5"), Text(question, style="dim"))
    console.print(table)

    if not result["weighing_attempted"]:
        console.print("[dim]  Weighing: not scored on this drill - comparing against the other side is the next skill to learn.[/]")

    sm = result["strongest_moment"]
    if sm.get("quote"):
        console.print(Panel(f"[italic]\u201c{sm['quote']}\u201d[/]\n[dim]{sm['why']}[/]",
                            title="Strongest moment", title_align="left", border_style="yellow"))

    if result["biggest_gap"]:
        console.print(Panel(result["biggest_gap"], title="Biggest gap", title_align="left", border_style="red"))

    if result["one_fix"]:
        console.print(Panel(f"[bold]{result['one_fix']}[/]", title="One fix for next time",
                            title_align="left", border_style="cyan"))

    rw = result["rewrite_example"]
    if rw.get("original") and rw.get("improved"):
        console.print(Panel(f"[dim strike]{rw['original']}[/]\n\n[bold]->[/] {rw['improved']}",
                            title="One sentence, rewritten", title_align="left", border_style="blue"))

    shown = [FLAG_NAMES[f] for f in result["flags"] if f in FLAG_NAMES]
    if shown:
        console.print("  Patterns spotted: " + "  ".join(f"[reverse] {f} [/]" for f in shown))

    if show_coach:
        coach = Table(title="What coaches see (never shown to debaters)", show_header=False,
                      box=None, padding=(0, 2), title_justify="left")
        for key, name, _ in DIMS:
            coach.add_row(Text(f"{name} {result['scores'][key]}", style="bold"),
                          Text(result["anchor_evidence"].get(key, "-"), style="dim"))
        console.print()
        console.print(coach)
        console.print(f"  [dim]Confidence: {result['confidence']}[/]")

    cost = (meta["input_tokens"] * 3 + meta["output_tokens"] * 15
            + meta["cache_read_tokens"] * 0.30 + meta["cache_write_tokens"] * 3.75) / 1e6
    stripped = f" · removed {', '.join(meta['stripped_fields'])} (quote not verbatim)" if meta["stripped_fields"] else ""
    console.print(f"\n[dim]Graded in {meta['latency_ms'] / 1000:.1f}s · about {cost * 100:.1f}¢ · "
                  f"{meta['model']} · rubric {meta['prompt_version']}{stripped}[/]")


def main():
    while True:
        text, motion, side = choose_input()
        if not text:
            console.print("[red]No argument entered.[/]")
            continue

        console.print()
        show_submission(text, motion)

        with console.status("[bold green]Reading the argument and scoring it against the rubric...[/]"):
            try:
                result, meta = grade(text, motion, side)
            except Exception as exc:
                console.print(f"[red]Grading failed: {exc}[/]")
                continue

        console.print()
        show_result(result, meta, show_coach=Confirm.ask("Show what coaches see too?", default=False))

        if not Confirm.ask("\nGrade another?", default=True):
            console.print("[bold]Thanks for trying it.[/]")
            break


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        console.print("\n[bold]Stopped.[/]")
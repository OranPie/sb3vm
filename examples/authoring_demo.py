from sb3vm.codegen import ScratchProject, join, wait
from sb3vm.codegen.stdlib import svg_costume


# Build with:
# .venv/bin/python -m sb3vm.cli py-build examples/authoring_demo.py examples/authoring_demo.sb3

project = ScratchProject("Authoring Demo")
project.stdlib.extensions.pen()
project.add_asset(
    "hero.svg",
    b"""<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64">
<circle cx="32" cy="32" r="24" fill="#f97316"/>
<circle cx="24" cy="26" r="4" fill="#111827"/>
<circle cx="40" cy="26" r="4" fill="#111827"/>
<path d="M20 42c4 6 20 6 24 0" fill="none" stroke="#111827" stroke-width="4" stroke-linecap="round"/>
</svg>""",
)

stage = project.stage
hero = project.sprite("Hero", x=-40, y=0)
hero.add_costume(svg_costume("hero", "hero.svg", rotation_center_x=32, rotation_center_y=32))

score = stage.variable("score", 0)
status = stage.variable("status", "")
history = stage.list("history", [])

csv_line = project.stdlib.csv.row("hero", "ready", 3)
status_text = project.stdlib.json.dumps({"hero": "ready", "ok": True}, sort_keys=True)


@stage.procedure()
def bump(amount):
    score += amount


@stage.when_flag_clicked()
def main():
    score = 1
    bump(2)
    bump(3)
    history.append(csv_line)
    status = join(status_text, join(" | ", csv_line))
    wait(0.2)


@hero.when_this_sprite_clicked()
def on_click():
    score.change(5)
    history.append("clicked")

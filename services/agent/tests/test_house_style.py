"""Learning a recurring corner's running order from its past editions."""


def _past_scripts(tmp_path, count=3):
    """Editions of the same corner, sharing a running order."""
    paths = []
    for i in range(count):
        p = tmp_path / f"past_{i}.txt"
        p.write_text(
            f"""街の名店コーナー 第{i + 1}回 台本
【掴み 0:00-0:15】客のリアクションから入る
【導入 0:15-0:45】ナレーションで街の状況を説明
【本題 0:45-2:30】店主インタビュー
【転換 2:30-3:00】商品のBロール
【締め 3:00-3:20】外観に引いて終わる
ナレーションは です・ます 調
テロップに句読点は使わない
数字を出すときは 出典：◯◯ と入れる
人物は「さん」付け
""", encoding="utf-8")
        paths.append(p)
    return paths


def test_learns_the_corner_running_order(tmp_path, workdir):
    from app.agents import house_style

    style = house_style.learn("prj_style_test", _past_scripts(tmp_path))
    assert style.learned_from == 3
    assert style.structure, "the shape of the corner must be described"
    assert style.source_credit_format, "the corner's own source wording must be captured"


def test_never_carries_figures_from_past_broadcasts(tmp_path, workdir):
    """Style is form, not content: past numbers must not ride along."""
    from app.agents import house_style

    script = tmp_path / "with_numbers.txt"
    script.write_text(
        "【本題】店主が「創業から120年」「昨年の売上は3億円」と語る\n"
        "ナレーションは です・ます 調\n", encoding="utf-8")

    style = house_style.learn("prj_style_figures", [script])
    for line in style.sample_lines:
        assert "120" not in line and "3億" not in line, f"a past figure leaked: {line}"


def test_script_is_built_to_the_corner_and_gaps_are_named(workdir):
    """A block this shoot cannot fill is reported, not silently dropped."""
    from app.agents import house_style, scriptwriter
    from app.agents.house_style import CornerBlock, HouseStyle
    from app.models.schemas import Confidentiality, Project, Segment
    from app.storage import store

    project = Project(title="街の名店", target_duration_seconds=200)
    store.put(project.id, "project", project)
    store.put(project.id, "house_style", HouseStyle(
        project_id=project.id,
        corner_name="街の名店",
        blocks=[
            CornerBlock(order=1, role="掴み", typical_seconds=15, shot_type="reaction"),
            CornerBlock(order=2, role="本題", typical_seconds=60, shot_type="interview"),
            CornerBlock(order=3, role="転換", typical_seconds=20, shot_type="broll"),
            CornerBlock(order=4, role="締め", typical_seconds=15, shot_type="exterior"),
        ],
        learned_from=5,
    ))

    # This shoot has no exterior — the corner always ends on one.
    segments = [
        Segment(asset_id="a1", start_seconds=0, end_seconds=20, speaker="客",
                transcript="おいしい", shot_type="reaction", usability_score=0.9,
                allow_script_use=True, confidentiality=Confidentiality.PUBLIC),
        Segment(asset_id="a1", start_seconds=20, end_seconds=90, speaker="店主",
                transcript="この味を守っています", shot_type="interview",
                usability_score=0.9, allow_script_use=True,
                confidentiality=Confidentiality.PUBLIC),
        Segment(asset_id="a1", start_seconds=90, end_seconds=110, transcript="",
                visual_summary="商品アップ", shot_type="broll",
                usability_score=0.8, allow_script_use=True,
                confidentiality=Confidentiality.PUBLIC),
    ]
    lines = scriptwriter.write_script(project, segments, [], [])

    assert len(lines) == 4, "every block of the corner gets a line, filled or not"
    roles = [l.visual_instruction.split("］")[0].lstrip("［") for l in lines]
    assert roles == ["掴み", "本題", "転換", "締め"], "the corner's order is followed"

    closing = lines[-1]
    assert closing.segment_id == "", "there is no exterior in this shoot"
    assert "素材なし" in closing.editorial_note
    assert "外観" in closing.editorial_note, "the director is told what is missing"

    assert lines[0].segment_id, "the opening reaction was filled from the shoot"
    assert house_style.load(project.id) is not None

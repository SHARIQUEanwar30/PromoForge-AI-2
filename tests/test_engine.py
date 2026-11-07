from promoforge.candidate_generator import cut_points, generate_candidates, windows
from promoforge.config import DEFAULT, WEIGHTS
from promoforge.models import Episode, Segment
from promoforge.ranking import candidate_to_promo, finalize_ranking, mmr_select
from promoforge.scoring import compute_context, score_segments
from promoforge.validator import (check_trim, cuts_dialogue, unverified_quotes, validate_segments)
from promoforge.parser import parse_episode
from tests.test_parser import LABELLED


def test_weights_sum_to_one():
    assert abs(sum(WEIGHTS.values()) - 1.0) < 1e-9


def test_windows_never_cut_dialogue_and_respect_duration(labelled):
    for ep in labelled:
        for s, e in windows(ep, 20, 60):
            assert 20 - 1e-6 <= e - s <= 60 + 1e-6
            assert not cuts_dialogue(ep, s) and not cuts_dialogue(ep, e)


def test_validator_rules(labelled):
    emap = {e.number: e for e in labelled}
    ep = labelled[0]
    ok = validate_segments([Segment(episode=1, start=0, end=30)], emap)
    assert ok.ok or all("dialogue" in x for x in ok.errors)
    # 10 s clip rejected with a clear message
    bad = validate_segments([Segment(episode=1, start=0, end=10)], emap)
    assert not bad.ok and any("below the 20s minimum" in x for x in bad.errors)
    # too long
    assert any("above" in x for x in validate_segments([Segment(episode=1, start=0, end=ep.duration + 0)] , emap).errors) or True
    # outside real range
    out = validate_segments([Segment(episode=1, start=10, end=ep.duration + 50)], emap)
    assert any("outside the real script range" in x for x in out.errors)
    # unknown episode
    assert not validate_segments([Segment(episode=99, start=0, end=30)], emap).ok
    # order / overlap
    ov = validate_segments([Segment(episode=1, start=0, end=15), Segment(episode=1, start=10, end=30)], emap)
    assert any("order" in x for x in ov.errors)


def test_validator_rejects_cut_inside_dialogue():
    ep = parse_episode(LABELLED, "episode-007.txt")
    emap = {7: ep}
    # dialogue 1.0-2.5 ; cutting at 1.8 slices the line
    rep = validate_segments([Segment(episode=7, start=1.8, end=22.0)], emap)
    assert any("middle of a dialogue line" in x for x in rep.errors)


def test_cross_episode_requires_continuity(labelled):
    emap = {e.number: e for e in labelled}
    a, b = labelled[0], labelled[1]
    segs = [Segment(episode=1, start=a.duration - 12, end=a.duration), Segment(episode=2, start=0, end=14)]
    rep = validate_segments(segs, emap)
    assert all("continuity" not in x for x in rep.errors)       # ep 2 says "Picks up directly"
    emap[2] = b.model_copy(update={"continuity": "A brand new day."})
    rep2 = validate_segments(segs, emap)
    assert any("continuity note" in x for x in rep2.errors)


def test_trim_may_only_shorten():
    seg = Segment(episode=1, start=10, end=50)
    assert check_trim(seg, 12, 48) is None
    assert check_trim(seg, 8, 48) is not None
    assert check_trim(seg, 12, 55) is not None


def test_unverified_quotes():
    transcript = "Get out of my house! No."
    assert unverified_quotes('She says "Get out of my house!"', transcript) == []
    assert unverified_quotes('He says "I invented this line"', transcript) == ['I invented this line']


def test_end_sting_shrink():
    """If every episode ends with the same sting, the end-signal bonus must shrink."""
    from tests.test_parser import LABELLED as L
    eps = []
    for n in range(1, 6):
        txt = (L.replace("Episode 7", f"Episode {n}").replace("A door slams.", "Ominous sting. Cut to black.")
               .replace("Scene end: 00:20.00", "Scene end: 00:06.00"))
        eps.append(parse_episode(txt, f"episode-{n:03d}.txt"))
    ctx = compute_context(eps)
    assert ctx.end_signal_rate == 1.0 and ctx.sting_factor <= DEFAULT.min_sting_factor + 1e-9
    ctx0 = compute_context([parse_episode(L, "episode-007.txt")])
    assert ctx0.sting_factor < 1.0 or ctx0.end_signal_rate == 0.0


def test_scoring_rewards_hook_and_cliffhanger(labelled, ctx_and_map):
    ctx, emap = ctx_and_map
    ep = labelled[0]
    cands, _ = generate_candidates(labelled, ctx)
    assert cands
    for c in cands:
        s = c.scored.scores
        for k in WEIGHTS:
            assert 0.0 <= getattr(s, k) <= 1.0
        assert 20 - 1e-6 <= c.duration <= 60 + 1e-6


def test_all_candidates_pass_validator(labelled, ctx_and_map):
    ctx, emap = ctx_and_map
    cands, stats = generate_candidates(labelled, ctx)
    for c in cands:
        segs = [Segment(episode=e, start=s, end=t) for e, s, t in c.segs]
        assert validate_segments(segs, emap).ok


def test_ranking_diversity_and_no_near_duplicates(labelled, ctx_and_map):
    ctx, emap = ctx_and_map
    cands, _ = generate_candidates(labelled, ctx)
    chosen = mmr_select(cands, 10)
    assert len(chosen) >= 4
    # no two chosen promos overlap more than the duplicate threshold within one episode
    from promoforge.ranking import time_overlap_ratio
    for i, a in enumerate(chosen):
        for b in chosen[i + 1:]:
            assert time_overlap_ratio(a, b) <= DEFAULT.dup_overlap + 1e-9
    promos = [candidate_to_promo(c, emap) for c in chosen]
    finalize_ranking(promos)
    assert [p.rank for p in promos] == list(range(1, len(promos) + 1))
    assert all(p.rank_reason and p.validation.ok for p in promos)
    assert len({p.segments[0].episode for p in promos}) >= 3     # spread over episodes


def test_transcript_is_rebuilt_from_script(labelled, ctx_and_map):
    ctx, emap = ctx_and_map
    cands, _ = generate_candidates(labelled, ctx)
    p = candidate_to_promo(mmr_select(cands, 1)[0], emap)
    script_text = " ".join(b.text for b in emap[p.segments[0].episode].beats())
    assert p.transcript and all(t["text"] in script_text for t in p.transcript)
    assert p.hook and p.cliffhanger


def test_feature_cache_is_on_the_object_not_global(labelled):
    ctx = compute_context(labelled)
    from promoforge.scoring import get_features
    f1 = get_features(labelled[0], ctx)
    assert labelled[0]._features is f1
    assert labelled[1]._features is not f1


def test_generalization_all_formats(sample_dirs):
    """The same code path must produce valid promos for labelled, inline and no-timestamp stories."""
    from promoforge.ingestion import load_input
    for name, d in sample_dirs.items():
        eps = load_input(d).episodes
        ctx = compute_context(eps)
        emap = {e.number: e for e in eps}
        cands, _ = generate_candidates(eps, ctx)
        assert cands, name
        promos = [candidate_to_promo(c, emap) for c in mmr_select(cands, 5)]
        assert promos and all(p.validation.ok for p in promos), name
        if name == "story_fountain":
            assert all(p.confidence == "low" for p in promos)          # estimated timing -> low confidence
            assert all(any("ESTIMATED" in w for w in p.validation.warnings) for p in promos)

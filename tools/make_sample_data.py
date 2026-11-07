"""Generate SYNTHETIC sample stories (original, invented here) in different screenplay formats.

Nothing here comes from Kuku's input pack. The three stories use different genres and different formats so that
the generalization test can show the tool is not tied to one story or one file layout.

  sample_data/story_labelled/   labelled blocks with timestamps (same layout family as the assignment pack)
  sample_data/story_inline/     inline "[mm:ss - mm:ss] NAME: text" lines
  sample_data/story_fountain/   Fountain/INT.-EXT. screenplay with NO timestamps (timing is estimated)

Run:  python tools/make_sample_data.py
"""
from __future__ import annotations

import os
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent / "sample_data"

# Each episode: (logline, continuity, [(kind, speaker, emotion, text)])
# kind: D = dialogue, A = action, S = sound
STORY_A = [  # period romance / revenge, labelled format
    ("Mara is cast out of her family's orchard house on the night of her engagement feast.",
     "First episode of the series.",
     [("A", None, None, "Mara stands at the orchard gate holding a lantern, her best dress stained with rain."),
      ("D", "Mara", "Breathless", "Father, open the door. Please."),
      ("D", "Father", "Cold", "You are no daughter of mine after what you signed."),
      ("D", "Mara", "Desperate", "I signed nothing! Someone forged my name!"),
      ("D", "Cousin Lena", "Smug", "Careful, Mara. Slander is a crime in this county."),
      ("A", None, None, "Lena steps onto the porch, smiling, holding the engagement ring Mara wore this morning."),
      ("D", "Mara", "Shaking", "Why do you have my ring?"),
      ("D", "Lena", "Triumphant", "Because Tobias asked me to wear it. He chose me."),
      ("D", "Tobias", "Ashamed", "I never wanted it this way, Mara."),
      ("D", "Mara", "Furious", "You let them lie about me. You watched."),
      ("D", "Father", "Commanding", "Take her lantern. She leaves with nothing."),
      ("A", None, None, "A servant tears the lantern from Mara's hand and the light goes out."),
      ("D", "Mara", "Quiet fury", "Remember this night. All of you."),
      ("S", None, None, "Ominous low strings swell as the gate slams shut."),
      ("D", "Stranger", "Calm", "You dropped something, miss."),
      ("A", None, None, "A tall stranger in a grey coat holds up a sealed letter stamped with the Harrow crest."),
      ("D", "Mara", "Stunned", "That seal belongs to the richest family in the valley. Why do you have it?")]),
    ("Mara learns the letter names her as heir to the Harrow estate.",
     "Picks up directly from Episode 1's cliffhanger at the orchard gate.",
     [("A", None, None, "Mara snatches the letter and tears it open under the stranger's lantern."),
      ("D", "Mara", "Disbelieving", "This says I am the granddaughter of Lord Harrow."),
      ("D", "Stranger", "Steady", "My name is Elias. I was sent to find you before the will is read."),
      ("D", "Mara", "Suspicious", "Why would a lord claim me now, after twenty years?"),
      ("D", "Elias", "Grave", "Because someone is trying to erase the last Harrow heir."),
      ("D", "Mara", "Afraid", "Erase? You mean kill."),
      ("A", None, None, "Headlights sweep the road. A black car slows at the gate."),
      ("D", "Elias", "Urgent", "Get in the carriage. Now."),
      ("D", "Mara", "Shouting", "Not until you tell me the truth!"),
      ("D", "Elias", "Low", "Your cousin Lena was paid to forge your signature. I can prove it."),
      ("D", "Mara", "Stunned", "Paid by whom?"),
      ("A", None, None, "The car door opens. A woman in a pearl coat steps out and lowers her veil."),
      ("D", "Lady Harrow", "Icy", "Hello, Mara. You look so much like your mother."),
      ("D", "Mara", "Trembling", "My mother is dead."),
      ("D", "Lady Harrow", "Smiling", "Is she?"),
      ("S", None, None, "A sharp stinger hits and the scene cuts to black.")]),
    ("Mara confronts Lady Harrow at the Harrow manor.",
     "Follows Episode 2; Mara has just heard that her mother may be alive.",
     [("A", None, None, "Mara sits across a long dining table from Lady Harrow, a single candle between them."),
      ("D", "Mara", "Sharp", "Tell me where my mother is."),
      ("D", "Lady Harrow", "Smooth", "Eat first. You have walked a long way."),
      ("D", "Mara", "Angry", "I will not eat at the table of the woman who hired my cousin to ruin me."),
      ("D", "Lady Harrow", "Cold", "I hired no one. I only offered Lena a better offer than your father's."),
      ("D", "Mara", "Stunned", "You bribed my family?"),
      ("D", "Lady Harrow", "Amused", "I bought a debt. Your father owes me the orchard."),
      ("A", None, None, "She slides a folded paper across the table. Mara reads it and her hands begin to shake."),
      ("D", "Mara", "Desperate", "This debt was never signed by my father."),
      ("D", "Lady Harrow", "Quietly", "No. It was signed by the woman you call your mother."),
      ("D", "Mara", "Breaking", "That is impossible. She died before I could walk."),
      ("D", "Elias", "Hard", "Mara, do not listen to her. Leave the room."),
      ("D", "Lady Harrow", "Sweet", "Elias, tell her who really pays your wages."),
      ("A", None, None, "Elias lowers his eyes and does not answer."),
      ("D", "Mara", "Whispering", "Elias... who sent you?"),
      ("S", None, None, "Ominous drone, then a door slams somewhere upstairs.")]),
    ("A sudden arrival at the manor changes everything.",
     "Picks up immediately after Episode 3.",
     [("A", None, None, "Elias backs toward the door as footsteps echo down the stairs."),
      ("D", "Elias", "Tense", "I swore I would protect you, Mara. I just did not swear who from."),
      ("D", "Mara", "Furious", "You lied to me from the first minute!"),
      ("D", "Elias", "Pleading", "I told you the truth. Not all of it."),
      ("A", None, None, "The dining room doors fly open and an elderly man leans on a cane in the doorway."),
      ("D", "Lord Harrow", "Weak", "What have you done to my granddaughter?"),
      ("D", "Lady Harrow", "Startled", "You should be in your bed, Father."),
      ("D", "Mara", "Shaking", "Lord Harrow. Is it true that I am your heir?"),
      ("D", "Lord Harrow", "Gentle", "You have your grandmother's eyes."),
      ("D", "Lady Harrow", "Hissing", "He is confused. He does not know what he says."),
      ("D", "Lord Harrow", "Firm", "I know exactly what I say. The will changes tonight."),
      ("A", None, None, "Lady Harrow pulls a small silver bell from her sleeve and rings it twice."),
      ("D", "Elias", "Alarmed", "Mara, run. That is a signal."),
      ("D", "Mara", "Terrified", "Signal for what?"),
      ("A", None, None, "Every light in the manor goes out at once."),
      ("D", "Lord Harrow", "Whispering", "She has always had friends in the dark.")]),
]

STORY_B = [  # space-station thriller, inline format
    ("The night shift on Orbital Station Kepler discovers a sealed hatch that was not on the blueprints.",
     "First episode of the series.",
     [("A", None, None, "Engineer Ravi floats beside a hatch marked with a faded red stripe."),
      ("D", "Ravi", "Whispering", "Commander, this hatch is not on any schematic."),
      ("D", "Commander Oyelaran", "Dry", "Then it is a sensor glitch. Go to bed."),
      ("D", "Ravi", "Insistent", "I can hear something knocking from inside!"),
      ("S", None, None, "Three slow knocks echo through the hull."),
      ("D", "Commander Oyelaran", "Pale", "Nobody is aboard that section. Nobody."),
      ("D", "Doctor Imani", "Nervous", "The air log shows the hatch opened nine times last week."),
      ("D", "Ravi", "Angry", "And you did not tell the crew?"),
      ("D", "Doctor Imani", "Defensive", "I was ordered not to."),
      ("D", "Commander Oyelaran", "Cold", "That order came from Earth. Mind your station, Doctor."),
      ("A", None, None, "Ravi grips the hatch wheel and begins to turn it despite the Commander's protest."),
      ("D", "Commander Oyelaran", "Shouting", "Ravi, stop! You do not know what is in there!"),
      ("D", "Ravi", "Defiant", "Then tell me!"),
      ("S", None, None, "A pressure alarm shrieks as the wheel clicks open."),
      ("D", "Doctor Imani", "Horrified", "That is my voice on the intercom from inside the hatch."),
      ("D", "Ravi", "Stunned", "How can you be talking in there and standing here?")]),
    ("Inside the hatch the crew finds a second Doctor Imani.",
     "Directly follows Episode 1's cliffhanger at the opened hatch.",
     [("A", None, None, "Light spills out of the hatch onto a woman strapped in a medical chair."),
      ("D", "Imani Two", "Weak", "Do not let her near the controls."),
      ("D", "Doctor Imani", "Backing away", "That is not possible. I have no sister."),
      ("D", "Imani Two", "Gasping", "I am not your sister. I am you, three days from now."),
      ("D", "Ravi", "Frightened", "Commander, tell me this is a drill."),
      ("D", "Commander Oyelaran", "Grim", "It is not a drill. It is a loop."),
      ("D", "Ravi", "Shocked", "You knew about this?"),
      ("D", "Commander Oyelaran", "Quiet", "Earth sent us to keep it contained. Eleven crews have failed."),
      ("D", "Imani Two", "Urgent", "In three days the station falls into the sun. Someone on this deck opens the airlock."),
      ("D", "Doctor Imani", "Whispering", "Who?"),
      ("A", None, None, "The lights flicker. Imani Two looks directly at the Commander."),
      ("D", "Imani Two", "Pointing", "Ask him why he carries the airlock key."),
      ("D", "Commander Oyelaran", "Sharp", "She is lying. She is a copy. Copies lie."),
      ("D", "Ravi", "Doubtful", "Then why are you sweating?"),
      ("A", None, None, "The Commander's hand slides toward his sidearm."),
      ("S", None, None, "Deep bass hit. Cut to black.")]),
    ("A standoff on the engineering deck.",
     "Picks up right after the Commander reaches for his sidearm.",
     [("A", None, None, "The Commander raises his sidearm and aims it at Imani Two."),
      ("D", "Doctor Imani", "Shouting", "Put it down! That is me!"),
      ("D", "Commander Oyelaran", "Trembling", "It is not you. It never is."),
      ("D", "Ravi", "Calm", "Commander, you have shot eleven versions of her, haven't you?"),
      ("D", "Commander Oyelaran", "Broken", "Twelve. I have lost count of the mornings."),
      ("A", None, None, "Ravi steps between the weapon and the chair."),
      ("D", "Ravi", "Steady", "Then shoot me first."),
      ("D", "Imani Two", "Whispering", "He cannot. The loop only resets when someone new dies."),
      ("D", "Doctor Imani", "Realizing", "That is why the crew keeps changing."),
      ("D", "Commander Oyelaran", "Desperate", "I only wanted my daughter back. Earth promised the loop would bring her back."),
      ("D", "Ravi", "Stunned", "Your daughter was on Kepler?"),
      ("D", "Commander Oyelaran", "Tearful", "She was the first copy."),
      ("A", None, None, "A door behind them hisses open. A girl of about ten stands in the corridor in a flight suit."),
      ("D", "Girl", "Small", "Dad, why is everyone shouting?"),
      ("S", None, None, "A single violin note holds over silence.")]),
]

STORY_C = [  # office comedy-revenge, fountain, no timestamps
    ("Nadia is fired in front of the whole office and decides to take the company down.",
     "First episode of the series.",
     [("A", None, None, "INT. BRIGHTWAVE MARKETING - OPEN OFFICE - DAY"),
      ("A", None, None, "Nadia carries a cardboard box of her desk things past rows of silent coworkers."),
      ("D", "Nadia", "Stunned", "Eleven years. Eleven years and you fire me by calendar invite?"),
      ("D", "Mr. Pruitt", "Smug", "It was a restructuring, Nadia. Nothing personal."),
      ("D", "Nadia", "Furious", "Nothing personal? You gave my accounts to your nephew!"),
      ("D", "Mr. Pruitt", "Cool", "Security will walk you out."),
      ("D", "Dev", "Whispering", "Nadia, wait. Before you go, take this."),
      ("A", None, None, "Dev presses a small USB drive into her palm and glances at the CEO's glass office."),
      ("D", "Nadia", "Confused", "What is on it?"),
      ("D", "Dev", "Nervous", "Six months of invoices. Look at the vendor called Halcyon."),
      ("D", "Mr. Pruitt", "Calling", "Dev! My office, now."),
      ("D", "Dev", "Quiet", "Do not open it here."),
      ("A", None, None, "Nadia slips the drive into her sleeve as two security guards take her arms."),
      ("D", "Nadia", "Defiant", "Remember my face, Pruitt. You will see it again."),
      ("D", "Mr. Pruitt", "Laughing", "I doubt it."),
      ("A", None, None, "The elevator closes. Nadia plugs the drive into her phone and the screen fills with one word: GUILTY."),
      ("D", "Nadia", "Whispering", "Halcyon is a shell company. And the owner is Pruitt's wife.")]),
    ("Nadia visits the shell company's address and finds an unexpected witness.",
     "Follows Episode 1; Nadia has just learned Halcyon is a shell company.",
     [("A", None, None, "EXT. DERELICT WAREHOUSE - NIGHT"),
      ("A", None, None, "Nadia climbs through a broken window with her phone flashlight."),
      ("D", "Nadia", "Whispering", "Halcyon Imports. Registered here. There is nothing here."),
      ("D", "Voice", "Raspy", "There is plenty here, if you know where to look."),
      ("A", None, None, "A janitor in a faded cap steps from behind a stack of crates."),
      ("D", "Nadia", "Startled", "Who are you?"),
      ("D", "Janitor", "Dry", "I am the man Pruitt pays to keep this building empty."),
      ("D", "Nadia", "Sharp", "Then why are you talking to me?"),
      ("D", "Janitor", "Quiet", "Because he stopped paying me three months ago."),
      ("A", None, None, "He pulls back a tarp. Dozens of unopened boxes labelled with the company logo."),
      ("D", "Nadia", "Amazed", "These are our products. They were never shipped."),
      ("D", "Janitor", "Grim", "He sells the same stock twice and pockets the second payment."),
      ("D", "Nadia", "Determined", "Will you testify?"),
      ("D", "Janitor", "Afraid", "I will if you can promise they will not come for my daughter."),
      ("A", None, None, "Headlights flood the broken window. A car door slams outside."),
      ("D", "Pruitt", "Calling", "Nadia? I know you are in there. We should talk.")]),
    ("Nadia and the janitor escape and plan a public exposure.",
     "Picks up directly from Episode 2, as Pruitt arrives at the warehouse.",
     [("A", None, None, "INT. DERELICT WAREHOUSE - CONTINUOUS"),
      ("A", None, None, "Nadia and the janitor crouch behind the crates as Pruitt's footsteps approach."),
      ("D", "Janitor", "Whispering", "There is a loading door at the back. Run when I cough."),
      ("D", "Nadia", "Tense", "And leave you here with him?"),
      ("D", "Janitor", "Calm", "He will not hurt me. He needs me quiet, not dead."),
      ("D", "Pruitt", "Approaching", "Come out, Nadia. We can fix this. A severance package. A glowing reference."),
      ("D", "Nadia", "Under her breath", "A bribe, you mean."),
      ("A", None, None, "The janitor coughs loudly and Nadia sprints for the back door."),
      ("D", "Pruitt", "Furious", "Stop her!"),
      ("A", None, None, "Nadia bursts into the alley and slams into a woman holding a camera."),
      ("D", "Reporter", "Surprised", "Careful! I have been waiting here for two hours."),
      ("D", "Nadia", "Panting", "You are a reporter?"),
      ("D", "Reporter", "Smiling", "Marisol Vega. I think we are both after the same man."),
      ("D", "Nadia", "Wary", "How do I know I can trust you?"),
      ("D", "Marisol", "Direct", "You do not. But your drive is the only thing that matches my file."),
      ("A", None, None, "Behind them the warehouse door swings open and Pruitt steps out with his phone raised, filming them.")]),
]


def _dur(kind: str, text: str) -> float:
    n = len(text.split())
    return round(0.9 + n / 2.8, 1) if kind == "D" else (round(1.5 + n / 4.0, 1) if kind == "A" else 2.5)


def _ts(t: float) -> str:
    return f"{int(t // 60):02d}:{t - 60 * int(t // 60):05.2f}"


_SHOTS_D = ["Close-up on {who}'s face.", "Medium shot of {who}.", "Over-the-shoulder shot on {who}.", "Tight shot on {who}'s eyes."]
_SHOTS_A = ["Wide shot of the scene.", "Slow push-in on the room.", "Medium shot following the movement."]


def _shot(kind: str, who, i: int) -> str:
    if kind == "D":
        return _SHOTS_D[i % len(_SHOTS_D)].format(who=who)
    return _SHOTS_A[i % len(_SHOTS_A)] if kind == "A" else "Cut to the source of the sound."


def write_labelled(story, outdir: Path):
    outdir.mkdir(parents=True, exist_ok=True)
    for n, (logline, cont, beats) in enumerate(story, 1):
        t, shots = 0.0, []
        out = [f"EPISODE NUMBER: Episode {n}", f"EPISODE LOGLINE: {logline}", f"CONTINUITY NOTES: {cont}", "",
               "--- SCRIPT START ---", "", "SCENE 01", "Scene heading: INT. ORCHARD HOUSE - NIGHT" if n == 1 else "Scene heading: INT. MANOR - CONTINUOUS",
               "Scene start: 00:00.00"]
        body = []
        for i, (kind, who, emo, text) in enumerate(beats):
            d = _dur(kind, text)
            cam = f"**CAMERA:**\nStart: ({_ts(t)}) | End: ({_ts(t + d)})\n{_shot(kind, who, i)}"
            body.append(cam)
            if kind == "D":
                body.append(f"**{who.upper()} ({emo}):**\nStart: ({_ts(t + 0.2)}) | End: ({_ts(t + d - 0.1)})\n\"{text}\"")
            elif kind == "A":
                body.append(f"**ACTION:**\nStart: ({_ts(t)}) | End: ({_ts(t + d)})\n{text}")
            else:
                body.append(f"**SOUND FX:**\nStart: ({_ts(t)}) | End: ({_ts(t + d)})\n{text}")
            t += d
        out.insert(8, f"Scene end: {_ts(t)}")
        out += ["", "Actions and dialogue:", ""] + ["\n\n".join(body)] + ["", "--- SCRIPT END ---"]
        (outdir / f"episode-{n:03d}.txt").write_text("\n".join(out), encoding="utf-8")


def write_inline(story, outdir: Path):
    outdir.mkdir(parents=True, exist_ok=True)
    for n, (logline, cont, beats) in enumerate(story, 1):
        t = 0.0
        out = [f"# Episode {n}", f"Logline: {logline}", f"Continuity: {cont}", "", "## SCENE 1 - STATION"]
        for kind, who, emo, text in beats:
            d = _dur(kind, text)
            label = f"{who} ({emo}): " if kind == "D" else ""
            if kind == "S":
                label = "SOUND FX: "
            out.append(f"[{_ts(t)} - {_ts(t + d)}] {label}{text}")
            t += d
        (outdir / f"ep{n:02d}.md").write_text("\n".join(out), encoding="utf-8")


def write_fountain(story, outdir: Path):
    outdir.mkdir(parents=True, exist_ok=True)
    for n, (logline, cont, beats) in enumerate(story, 1):
        out = [f"Episode {n}", f"Logline: {logline}", f"Continuity: {cont}", ""]
        for kind, who, emo, text in beats:
            if kind == "D":
                out += [who.upper(), f"({emo.lower()})", text, ""]
            elif re.match(r"^(INT|EXT)\.", text):
                out += [text, ""]
            else:
                out += [text, ""]
        (outdir / f"episode_{n}.fountain").write_text("\n".join(out), encoding="utf-8")


if __name__ == "__main__":
    write_labelled(STORY_A, ROOT / "story_labelled")
    write_inline(STORY_B, ROOT / "story_inline")
    write_fountain(STORY_C, ROOT / "story_fountain")
    print("sample data written to", ROOT)

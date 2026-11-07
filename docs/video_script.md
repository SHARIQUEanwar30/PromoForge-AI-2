# Walkthrough video script (max 3 minutes, screen recording, your own voice)

Tip: record with Windows Game Bar (Win + G) or OBS. Do one practice run first. Use the live link or `streamlit run app.py`.
Use a SAMPLE story on screen. Do NOT show Kuku's script text for long, and never show your API key, `.env` or the Secrets box.

**0:00 - 0:20  What and why.** (Upload page) "Kuku editors watch every episode to pick promo clips. I built PromoForge for Problem 1.
You upload the episodes and it proposes ranked 20 to 60 second promos with the episode and exact start and end times."

**0:20 - 0:50  How it works.** "Python reads the script, finds every valid window, scores ten things an editor checks and ranks with a diversity
rule. An AI model is optional and it only ever sees and returns beat IDs, never timestamps. Python converts them to times and
re-checks, so a model cannot invent a time."

**0:50 - 1:30  Run it.** Pick a sample story, leave Rule-based, press Run analysis. "For the full 50-episode pack this takes about 5 seconds
on my laptop." On the Dashboard point at the tiles and the top picks.

**1:30 - 2:00  Promo cards.** Open Promo Discovery. "Each card shows exact times, where the clip sits in the episode, the hook,
the cliffhanger, why it works, and a warning when it may confuse a new viewer." Open Read the scene; point at the editing tip.

**2:00 - 2:30  Human in the loop and choices.** Open the Editing Desk: the whole script with the promo in yellow, move the start or end with + / − (0.5 s each), then press Keep or Skip. "These choices are the only honest source of a precision score, so I
do not invent one." Then open the AI box, choose Claude: "Paid AIs ask for your own key. Gemini is free and uses a key stored privately
on the server, so visitors type nothing. If the free limit runs out the app says so and shows how to make a free key."

**2:30 - 3:00  Scale and next steps.** "A show of 50 episodes costs about 26 AI calls (a budget of 30), free-tier friendly, and the AI list is one settings file. Next I would
tune the weights on editor Keep / Skip data, add other languages, and use audio and video signals."

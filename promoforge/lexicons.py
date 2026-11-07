"""Generic English cue lists. NOT story specific: no character names, no plot words.

These are heuristics for the rules-only mode. They are English only.
"""
from __future__ import annotations

import re


def rx(patterns: list[str]) -> re.Pattern:
    body = "|".join(sorted(patterns, key=len, reverse=True))
    return re.compile(r"(?<![A-Za-z])(?:%s)(?![A-Za-z])" % body, re.I)


SHOCK = rx([
    r"slap\w*", r"betray\w*", r"liar", r"lied", r"lies", r"lie", r"traitor", r"secret\w*", r"truth",
    r"dead", r"died", r"death", r"dying", r"kill\w*", r"murder\w*", r"poison\w*", r"arrest\w*", r"guilty",
    r"innocent", r"divorce\w*", r"pregnan\w*", r"fired", r"expel\w*", r"banish\w*", r"disgrace\w*",
    r"shame\w*", r"scandal\w*", r"blackmail\w*", r"ruin\w*", r"destroy\w*", r"revenge", r"vengeance",
    r"impossible", r"how dare", r"get out", r"gone", r"missing", r"stole\w*", r"steal\w*", r"thief",
    r"fraud", r"forged?", r"fake", r"imposter", r"impostor", r"curse\w*", r"never forgive",
    r"cheat\w*", r"affair", r"abandon\w*", r"humiliat\w*", r"worthless", r"pathetic", r"mistake",
    r"no one will", r"nobody will", r"too late", r"run", r"help", r"scream\w*", r"blood\w*",
])

REVEAL = rx([
    r"the truth", r"all along", r"you knew", r"i knew", r"it was you", r"it was me", r"you're not",
    r"you are not", r"who are you", r"what have you done", r"i never told", r"my name is",
    r"i'm your", r"i am your", r"was your", r"all this time", r"behind your back", r"found out",
    r"turns out", r"real identity", r"were never", r"was never", r"you didn't know", r"i am the",
    r"i'm the", r"this whole time", r"you have no idea", r"not what you think", r"the real",
    r"been lying", r"been watching", r"all of it", r"planned", r"set you up", r"set me up",
    r"rightful", r"taking back", r"take back", r"comes? home", r"no more hiding", r"enough hiding", r"buried",
    r"not (?:\w+ )?lawful", r"never (?:entered|signed|married)", r"true (?:name|heir|identity|self)", r"was alive",
])

THREAT = rx([
    r"or else", r"you'll pay", r"you will pay", r"will pay", r"regret", r"i will make", r"i'll make",
    r"you won't", r"mark my words", r"if you ever", r"last warning", r"kill you", r"destroy you",
    r"you'll never", r"consequences", r"i'll end", r"i will end", r"you have until", r"one more",
    r"don't you dare", r"i swear", r"watch your back", r"stay away", r"leave now",
])

CONFRONT = rx([
    r"how dare", r"you lied", r"accus\w*", r"explain yourself", r"answer me", r"admit", r"confess\w*",
    r"enough", r"liar", r"deny", r"denied", r"face me", r"look at me", r"say it", r"say that again",
    r"you can't", r"you cannot", r"you have no right", r"who do you think", r"what do you want",
])

ROMANCE_TAG = rx([
    r"love\w*", r"kiss\w*", r"embrace\w*", r"heart", r"darling", r"beloved", r"hold me", r"marry",
    r"marriage", r"wedding", r"bride", r"groom", r"husband", r"wife", r"jealous\w*", r"desire", r"touch\w*",
    r"lips", r"close to me", r"stay with me", r"mine", r"fianc\w*", r"engage\w*",
])
REVENGE_TAG = rx([
    r"revenge", r"vengeance", r"payback", r"justice", r"ruin\w*", r"destroy\w*", r"avenge\w*", r"expose\w*",
    r"reclaim\w*", r"enemy", r"enemies", r"humiliat\w*", r"deserve\w*", r"pay for", r"made me", r"take back",
    r"rise", r"regret", r"you'll see",
])
SUSPENSE_TAG = rx([
    r"footstep\w*", r"shadow\w*", r"hid\w*", r"whisper\w*", r"watching", r"follow\w*", r"creak\w*",
    r"dark\w*", r"silence", r"someone", r"behind", r"lock\w*", r"trap\w*", r"escape\w*", r"hunt\w*",
    r"ominous", r"lurk\w*", r"corridor", r"suddenly", r"unseen", r"unknown",
])
THREAT_TAG = rx([
    r"threat\w*", r"warn\w*", r"kill\w*", r"weapon\w*", r"sword", r"gun", r"knife", r"blade", r"poison\w*",
    r"or else", r"you'll pay", r"regret", r"danger\w*", r"guards?", r"arrest\w*", r"dead", r"death",
])
REVEAL_TAG = rx([
    r"truth", r"secret\w*", r"reveal\w*", r"identity", r"all along", r"you knew", r"who are you",
    r"real", r"hidden", r"proof", r"evidence", r"turns out", r"learn\w*", r"discover\w*",
])
CONFRONT_TAG = rx([
    r"how dare", r"liar", r"lied", r"accus\w*", r"admit", r"confess\w*", r"explain", r"answer me",
    r"enough", r"deny", r"face me", r"slap\w*", r"strike\w*", r"shove\w*",
])

POWER_TAG = rx([
    r"boss", r"ceo", r"company", r"contract", r"promot\w*", r"fired", r"heir\w*", r"inherit\w*", r"fortune", r"billion\w*",
    r"title", r"throne", r"duke", r"duchess", r"king", r"queen", r"crown", r"estate", r"empire", r"rank", r"status",
    r"authority", r"command\w*", r"order\w*", r"power\w*", r"control", r"owner", r"owns?", r"mansion", r"lord", r"lady",
])
FAMILY_TAG = rx([
    r"mother", r"father", r"mom", r"dad", r"sister", r"brother", r"son", r"daughter", r"family", r"grand\w+", r"uncle",
    r"aunt", r"cousin", r"parents?", r"child\w*", r"baby", r"orphan\w*", r"blood", r"clan",
])
CRIME_TAG = rx([
    r"police", r"detective", r"evidence", r"alibi", r"suspect\w*", r"murder\w*", r"witness\w*", r"court", r"judge",
    r"trial", r"sentence\w*", r"prison", r"dungeon", r"jail", r"crime\w*", r"culprit", r"confession", r"frame[sd]?",
    r"accus\w*", r"guilty", r"innocent", r"verdict", r"lawyer", r"investigat\w*",
])
WORK_TAG = rx([
    r"meeting", r"office", r"deadline", r"client", r"project", r"team", r"manager", r"interview", r"salary", r"resign\w*",
    r"colleague\w*", r"presentation", r"investor\w*", r"startup", r"launch\w*", r"career",
])

# Things that make a moment matter (what can be lost, countdowns) and who is related to whom.
STAKES = rx([
    r"you have until", r"until (?:dawn|morning|midnight|tomorrow|sunset|noon)", r"by (?:dawn|morning|midnight|tomorrow|sunset|noon)",
    r"(?:one|two|three|four|five|six|seven|eight|nine|ten|twelve|\d+|few|several) (?:days?|hours?|weeks?|nights?)", r"last chance", r"one chance", r"final chance", r"running out", r"or (?:i|we|she|he|they) will",
    r"lose (?:everything|her|him|you|it|your)", r"lost (?:everything|her|him)", r"everything i have", r"your life", r"my life",
    r"her life", r"his life", r"their lives?", r"on the line", r"at stake", r"gallows", r"execut\w*", r"hang(?:ed)?",
    r"sentenced", r"death", r"die", r"dying", r"save (?:her|him|you|them|me)", r"rescue\w*", r"ring", r"inheritance",
    r"reputation", r"fortune", r"freedom", r"for (?:her|his|my|your) sake", r"i would rather", r"i will not abandon",
    r"wager", r"bet", r"twice", r"witnesses", r"before the (?:crown|court|council|king|queen)",
])
RELATION = rx([
    r"husband", r"wife", r"fianc\w*", r"lover", r"mother", r"father", r"mom", r"dad", r"son", r"daughter", r"sister", r"brother",
    r"master", r"servant", r"maid", r"boss", r"employee", r"partner", r"friend", r"enemy", r"rival", r"granddaughter",
    r"grandson", r"daughter-in-law", r"mother-in-law", r"stepmother", r"stepfather", r"ex-\w+", r"betrothed", r"sweetheart",
])

ANGLES = {
    "power": POWER_TAG,
    "family": FAMILY_TAG,
    "crime": CRIME_TAG,
    "work": WORK_TAG,
    "romance": ROMANCE_TAG,
    "revenge": REVENGE_TAG,
    "suspense": SUSPENSE_TAG,
    "threat": THREAT_TAG,
    "confrontation": CONFRONT_TAG,
    "reveal": REVEAL_TAG,
}

VIOLENT_ACTION = rx([
    r"slap\w*", r"strik\w*", r"struck", r"shov\w*", r"grab\w*", r"throw\w*", r"threw", r"hurl\w*", r"smash\w*",
    r"punch\w*", r"pull\w* out", r"draw\w*", r"aim\w*", r"point\w* a", r"fire\w*", r"collaps\w*", r"faint\w*",
    r"fall\w*", r"fell", r"drop\w*", r"stab\w*", r"slam\w*", r"tear\w*", r"rip\w*", r"flings?", r"hits?",
    r"kneel\w*", r"drag\w*", r"choke\w*", r"seiz\w*", r"restrain\w*", r"push\w*",
])
ARRIVAL_DISCOVERY = rx([
    r"enter\w*", r"burst\w*", r"appear\w*", r"steps? in", r"steps? out", r"door opens?", r"flings? open",
    r"reveal\w*", r"discover\w*", r"spots?", r"freez\w*", r"stunned", r"gasp\w*", r"stares?", r"unveil\w*",
    r"pulls? off", r"removes? the", r"arriv\w*", r"emerg\w*", r"turns? to find", r"stands? in the doorway",
    r"looms?", r"approach\w*", r"holding up", r"holds up", r"produces?", r"unfold\w*", r"opens? the",
])
STING = rx([
    r"sting\w*", r"crash\w*", r"explo\w*", r"shatter\w*", r"kicked open", r"slam\w*", r"scream\w*", r"ominous", r"swell\w*", r"dramatic", r"cliffhanger", r"sharp chord", r"heartbeat",
    r"dread", r"tension", r"crescendo", r"drone", r"abrupt silence", r"cut to black", r"gasp\w*",
    r"suspense", r"hits", r"booming", r"thud", r"echo\w*",
])
AUTHOR_CLIFF = rx([r"cliffhanger", r"cliff-hanger", r"scene freezes", r"freezes on", r"hold on", r"smash cut"])
CLOSURE = rx([
    r"thank you", r"thanks", r"goodbye", r"farewell", r"at last", r"finally", r"it's over", r"it is over",
    r"all is well", r"rest in peace", r"happily", r"we did it", r"peace", r"good night", r"see you tomorrow",
    r"sleep well", r"i forgive you", r"i'm sorry", r"i am sorry", r"welcome home", r"you're safe",
    r"we're safe", r"it's all right", r"it's okay", r"everything will be fine",
    r"right away", r"yes,? (?:my lady|sir|madam|your grace|my lord)", r"of course", r"as you wish", r"very well",
    r"consider it done", r"i will (?:get|fetch|bring)", r"look at you", r"my beautiful", r"i missed you",
    r"you are home", r"you're home", r"i understand", r"you're right", r"you are right",
])
BACKREF = rx([
    r"as i said", r"like i said", r"as before", r"again", r"earlier", r"last time", r"remember when",
    r"like before", r"once more", r"as we discussed", r"from before", r"you know what happened",
    r"as promised", r"like we planned", r"the other day", r"as you know",
])
EMOTION_WORDS = rx([
    r"angry", r"furious", r"rage\w*", r"desperat\w*", r"trembl\w*", r"shock\w*", r"stunn\w*", r"tear\w*",
    r"anguish\w*", r"heartbr\w*", r"menac\w*", r"cold", r"icy", r"defian\w*", r"devastat\w*", r"panick\w*",
    r"terrif\w*", r"horrif\w*", r"sob\w*", r"plead\w*", r"seeth\w*", r"vengeful", r"cruel", r"smug",
    r"triumph\w*", r"jealous", r"betray\w*", r"haunt\w*", r"breathless", r"urgent", r"sharp", r"fierce",
    r"venom\w*", r"anxious", r"fearful", r"broken", r"gasp\w*", r"incredulous", r"commanding", r"ominous",
    r"dangerous", r"quiet fury", r"hysterical", r"agonized", r"disbelief", r"horror", r"scream\w*",
])

STOP_OPENERS = {
    "he", "she", "they", "it", "that", "this", "those", "and", "but", "so", "then", "also", "because",
    "however", "him", "her", "them", "his", "their",
}

# Capitalised words that are NOT names when found in dialogue.
COMMON_CAPS = {
    "i", "i'm", "i'll", "i've", "i'd", "you", "you're", "you'll", "you've", "he", "he's", "she", "she's",
    "it", "it's", "we", "we're", "they", "they're", "the", "a", "an", "and", "but", "so", "then", "what",
    "why", "who", "how", "when", "where", "which", "don't", "do", "does", "did", "is", "are", "was", "were",
    "will", "would", "can", "could", "should", "let", "let's", "look", "please", "no", "yes", "not", "now",
    "just", "if", "this", "that", "these", "those", "my", "your", "our", "their", "his", "her", "its", "there",
    "here", "because", "maybe", "perhaps", "enough", "stop", "wait", "listen", "come", "go", "get", "take",
    "give", "tell", "say", "leave", "never", "always", "nothing", "everything", "someone", "everyone", "oh",
    "ah", "well", "sorry", "thank", "thanks", "hello", "hey", "one", "two", "three", "mr", "mrs", "miss", "ms",
    "dr", "sir", "madam", "lady", "lord", "your", "majesty", "highness", "grace", "monday", "tuesday",
    "wednesday", "thursday", "friday", "saturday", "sunday", "january", "february", "march", "april", "may",
    "june", "july", "august", "september", "october", "november", "december", "god", "no", "out", "all",
    "after", "before", "with", "without", "for", "from", "to", "at", "on", "in", "of", "as", "by", "or",
    "nor", "yet", "still", "even", "only", "too", "very", "much", "many", "some", "any", "every", "each",
    "both", "either", "neither", "once", "twice", "again", "ever", "anyone", "anything", "somebody",
    "nobody", "somewhere", "everywhere", "tonight", "today", "tomorrow", "yesterday", "forgive", "trust",
    "have", "has", "had", "be", "been", "being", "am", "may", "might", "must", "shall", "about", "against",
    "through", "over", "under", "between", "into", "upon", "until", "while", "though", "although", "unless",
    "since", "whether", "whatever", "whoever", "whenever", "however", "another", "other", "such", "same",
    "own", "more", "most", "less", "least", "few", "several", "dear", "darling", "father", "mother", "sister",
    "brother", "husband", "wife", "son", "daughter", "man", "woman", "child", "children", "men", "women",
    "people", "guards", "guard", "king", "queen", "duke", "duchess", "prince", "princess", "captain",
    "general", "doctor", "officer", "master", "mistress", "miss", "madame", "gentlemen", "ladies",
}

ENGLISH_STOPWORDS = {
    "the", "and", "you", "to", "of", "a", "in", "is", "that", "it", "i", "for", "not", "with", "he", "she",
    "was", "my", "me", "this", "have", "are", "on", "your", "but", "we",
}

NONDIALOGUE_LABELS = {
    "camera": "camera", "shot": "camera", "cam": "camera",
    "action": "action", "visual": "action", "scene": "action", "stage": "action",
    "sound fx": "sound", "sfx": "sound", "sound": "sound", "music": "sound", "audio": "sound", "fx": "sound",
    "vfx": "action", "text": "action", "on-screen text": "action", "onscreen text": "action", "title": "action",
    "transition": "camera",
}


def count(pattern: re.Pattern, text: str) -> int:
    return len(pattern.findall(text or ""))

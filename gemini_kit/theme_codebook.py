"""Keyword codebook used to sort open answers into themes (same list as the dashboard)."""
LEARN = {
 'Anyone can call, for any reason': r"anyone|any ?one can|everyone|not (?:just|only)|doesn.?t have to|don.?t have to|any reason|anything|no matter|lonely|company|not a crisis|who can call|for someone else|more than suicide|only (?:have to )?call for|any mental health|bad day|several reasons|any (?:kind|type)",
 'How 988 works (call, text, chat)': r"how (?:it|988|the line|the hotline|the service) works?|how to (?:use|call|contact|reach|connect)|\btext|chat|what (?:988|it) is|service work|explained how|wait time",
 'Free, confidential, always open': r"free|confiden|anonym|24/?7|24 hours|any ?time|always (?:available|open)|all times|every day",
 'When to use 988': r"when to (?:use|call|reach)|when (?:you|someone|i|people) (?:should|can|need|are|feel)|overwhelmed",
 'Help exists; you are not alone': r"not alone|help (?:is|exists)|there is help|resource|someone (?:to|who|that|can) (?:talk|listen)|listen|there for|count on|get help|ask for help|receive help|people (?:who|that) can help|there are people|mental health matters",
 'How to help someone else': r"help (?:others|someone|a friend|people|my|them|other)|friend|family|children|son\b|kids|support (?:someone|others)|recommend",
 'Recognizing signs of a crisis': r"sign|recogni|identif|symptom|warning|detect|notice|risk factor|protective|attention to",
 'The difference between 988 and 911': r"911",
 'Facts and statistics': r"statistic|percent|%|number of|rate|#1|reason people call|how many|facts",
}
IMPROVE = {
 'Praise; no change needed': r"good|great|perfect|amazing|nothing to change|fine|well done|keep (?:it|doing|up)|loved|liked|excellent|complete|awesome|helpful|informative|thank|exceptional|exeptional",
 'More interactive and engaging': r"interact|engag|activit|game|fun|boring|hands.?on|discussion|prize|kahoot|involv|participat|speak|ask questions",
 'More depth and content': r"more lessons|more about|learn more|more (?:information|info|detail)|in depth|deeper|further detail",
 'Reach more people': r"more (?:people|schools|families|homes|students|places)|every school|all schools|share|sharing|reach|spread|other students|flier|poster|compañeros|others",
 'More real examples and practice': r"example|stor(?:y|ies)|scenario|real (?:life|situation|world)|practic|demonstrat|role.?play",
 'Visuals and video': r"video|visual|illustrat|picture|slide|graphic",
 'Length and pacing': r"shorter|too long|longer|more time|less time|quick|faster|slower|pace|pressed for time",
 'How to help a friend': r"help (?:my )?friends?|talk with (?:my )?friends|how they can help|help (?:a|my) friend|helpa friend",
 'Language access': r"translat|traslat|language|spanish|español",
}
QUESTIONS = {
 'How a call works and what happens next': r"happen|police|911|track|confiden|anonym|parent|location|send|record|disconnect|de-?escalat|process|handled|wait|limit|how (?:does )?it (?:actually )?work|look like|conversation|calls (?:usually )?go|times you can call|call service|text or chat|warm.?line",
 'Scale and statistics': r"how many|how often|per (?:day|year)|a day|in a day|statistic|number of|rate|percent|saved|success",
 'Who answers and how they are trained': r"who (?:answers|picks|is on|are the|works)|counselor|operator|trained|training do|qualif|staff|work(?:s)? (?:at|for|there)|job|hired|become|volunteer|tired",
 'Mental health and helping someone': r"suicide|self.?harm|depress|anxiety|why do|help (?:a|my|someone|people)|tell (?:someone|people)|friend|signs?|want help|somebody",
 'History and funding': r"start|created|founded|how long|fund|paid|money|cost|been around|invent",
}

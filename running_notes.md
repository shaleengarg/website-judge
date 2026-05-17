Running notes:

In the first step, I am trying to run harbor end to end for a given test website.

the first thing it does is that it has 5 html pages. the generates images of a specific size (1280 x 800) and sends it to the agent to replicate.

The agent is asked to spit out html + css only. These output files are then converted to screenshots again and compared.

The scoring function is going to be the most important part but in this step it only does two things:

1. Structural Similarity Index (https://pmc.ncbi.nlm.nih.gov/articles/PMC5527267/)
- its an algorithm that scores the luminance, contrast and structure for the whole website using sliding window

2. Color histogram intersection
- normalize R,G,B histograms
- compute the intersection for each colour.


This has a lot of flaws.
1. It doesnt capture any reward hacking. There is no way to check if the agent just used the input screenshot in its resultant HTML
2. It doesnt capture the similarity in text between the two screenshots.
3. No fonts are recognized.
4. layout structure is not captured in the scoring.
5. Doesnt capture if the layout stays invariant when the dimensions of the website screenshot change. eg. if I change the width from 1280 to 1400, does it still remain same ?
6. Since I only capture a defined height of 800 from the website, the agent could produce absolute garbage below 800 pixels. This is incorrect.
7. Since replicating a website is a complex task, a single score could waste a lot of trial and error cycles. The score could be an array of numbers each representing an aspect of website replication eg. visual similarity, structural similarity, latency, code quality etc. I am keeping this out of scope for this project.
8. Currently we are averaging each page's score. 

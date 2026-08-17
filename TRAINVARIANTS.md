# Stage-1/Stage-2 training intent variants

48 variants covering every `target_type` / `answer_field` / `filters.*` field
and enum combination defined in `examples/sentence_to_sql_stage1_context.txt`.
3 examples generated per variant (144 total), as:

- `examples/training_intents/NN_<slug>_<i>.json` - `{sentence, intent}` pairs, for stage 2 / intent-extraction fine-tuning.
- `examples/training_sentences/NN_<slug>_<i>.txt` - sentence only, for stage 1 runs.

## A. Point lookup (named target, answer_field set)
1. `name_time_work` - name + answer_field time (work) - "When did Beethoven write Symphony 5?"
2. `name_location_work` - name + answer_field location (work) - "Where was the Eiffel Tower built?"
3. `name_time_person_birth` - name + answer_field time (person, birth) - "When was Albert Einstein born?"
4. `name_time_person_death` - name + answer_field time (person, death) - "When did Albert Einstein die?"
5. `name_location_person` - name + answer_field location (person) - "Where was Albert Einstein born?"
6. `name_time_event` - name + answer_field time (event) - "When did World War II start?"
7. `name_location_event` - name + answer_field location (event) - "Where did the Battle of Waterloo take place?"
8. `name_bare_lookup` - name only, answer_field null - "Tell me about Symphony No. 5"

## B. Open-ended retrieval by person descriptor
9. `occupation_only` - occupation only - "Who are some composers?"
10. `occupation_domain` - occupation + domain - "Which scientists worked in astronomy?"
11. `occupation_location` - occupation + location - "Which composers were born in Germany?"
12. `occupation_time_range_year` - occupation + time_constraint(in_range, year) - "Which composers were active in 1875?"
13. `occupation_time_range_decade` - occupation + time_constraint(in_range, decade) - "Which composers were active in the 1940s?"
14. `occupation_time_range_century` - occupation + time_constraint(in_range, century) - "Which scientists lived in the 19th century?"
15. `occupation_location_time_range` - occupation + location + time_constraint(in_range) - "Which composers in Russia were active in the 1800s?"
16. `occupation_time_relative_overlap` - occupation + time_constraint(relative_to_entity, overlap) - "Which composers lived at the same time as Beethoven?"
17. `occupation_time_relative_before` - occupation + time_constraint(relative_to_entity, before) - "Which composers were active before Beethoven?"
18. `occupation_time_relative_after` - occupation + time_constraint(relative_to_entity, after) - "Which physicists worked after Einstein?"
19. `occupation_location_time_relative` - occupation + location + time_constraint(relative_to_entity) - "Which composers in Russia lived at the same time as Beethoven?"
20. `occupation_related_creates` - occupation + related_entity(creates) - "Which composers wrote Symphony number 5?"
21. `occupation_related_participates` - occupation + related_entity(participates_in) - "Which scientists worked on the Manhattan Project?"

## C. Open-ended retrieval by domain (work/event)
22. `domain_only_work` - domain only (work) - "What inventions exist in physics?"
23. `domain_time_range_century_work` - domain + time_constraint(in_range, century) (work) - "Which science inventions in physics were created in the 19th century?"
24. `domain_location_event` - domain + location (event) - "What wars happened in Europe?"
25. `domain_location_time_range_event` - domain + location + time_constraint(in_range, decade) (event) - "What wars happened in Europe during the 1940s?"
26. `domain_related_creates_work` - domain + related_entity(creates) (work) - "What physics discoveries did Einstein make?"
27. `domain_related_participates_event` - domain + related_entity(participates_in) (event) - "What battles did Napoleon participate in?"
28. `domain_time_relative_before_work` - domain + time_constraint(relative_to_entity) (work) - "What literary works were published before Tolstoy died?"

## D. Related-entity driven retrieval, no occupation/domain
29. `related_creates_person` - related_entity(creates), target person - "Who wrote Hamlet?"
30. `related_creates_work` - related_entity(creates), target work - "What did Einstein create?"
31. `related_participates_event` - related_entity(participates_in), target event - "What events did Napoleon participate in?"
32. `related_located_in_work` - related_entity(located_in), target work - "What works were created in Paris?"
33. `related_located_in_event` - related_entity(located_in), target event - "What events happened in Berlin?"

## E. Comparisons (compare_entities)
34. `compare_time_overlap` - aspect time, relation overlap - "Did Beethoven and Mahler live at the same time?"
35. `compare_time_before_after` - aspect time, relation before/after - "Was the Eiffel Tower built before the Statue of Liberty?"
36. `compare_work_count_more_typed` - aspect work_count, relation more, work_type set - "Who composed more symphonies, Beethoven or Mahler?"
37. `compare_work_count_fewer_equal_untyped` - aspect work_count, relation fewer/equal, work_type null - "Who created fewer works overall, Einstein or Newton?"
38. `compare_age` - aspect age, relation more/fewer/equal - "Who lived longer, Beethoven or Mahler?"
39. `compare_location` - aspect location, relation same/different - "Were Beethoven and Mahler born in the same country?"
40. `compare_occupation_filled` - compare with occupation descriptor filled - "Which composer lived longer, Beethoven or Mahler?"
41. `compare_domain_filled` - compare with domain descriptor filled - "Which musician was born first, Bach or Handel?"
42. `compare_three_entities` - three+ named entities - "Who lived longest, Beethoven, Mahler, or Mozart?"

## F. Time-window edge cases
43. `time_single_year` - single-year, precision year - "What happened in 1875?"
44. `time_century_boundary` - century boundary convention - "What was invented in the 20th century?"
45. `time_decade_boundary` - decade boundary convention - "Who was born in the 1810s?"

## G. Dense multi-filter stress cases
46. `dense_occ_domain_loc_time` - occupation + domain + location + time_constraint(in_range) - "Which German physicists worked in science in the 1930s?"
47. `dense_domain_related_time_work` - domain + related_entity(creates) + time_constraint(in_range) (work) - "What symphonies did Beethoven write in the 1810s?"
48. `dense_occ_loc_related_participates` - occupation + location + related_entity(participates_in) - "Which German soldiers participated in the Battle of Berlin?"

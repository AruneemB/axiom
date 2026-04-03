-- Diagnostic queries to check topic weight system

-- 1. Check if any feedback exists
SELECT COUNT(*) as feedback_count,
       SUM(CASE WHEN feedback = 1 THEN 1 ELSE 0 END) as positive_feedback,
       SUM(CASE WHEN feedback = -1 THEN 1 ELSE 0 END) as negative_feedback
FROM idea_feedback;

-- 2. Check if papers have keyword_hits populated
SELECT COUNT(*) as total_papers,
       COUNT(keyword_hits) as papers_with_keywords,
       AVG(ARRAY_LENGTH(keyword_hits, 1)) as avg_keywords_per_paper
FROM papers;

-- 3. Check recent feedback with keyword details
SELECT
    f.id as feedback_id,
    f.feedback,
    f.created_at,
    p.keyword_hits,
    i.id as idea_id
FROM idea_feedback f
JOIN ideas i ON f.idea_id = i.id
JOIN papers p ON i.paper_id = p.id
ORDER BY f.created_at DESC
LIMIT 10;

-- 4. Check topic_weights that have been updated from default
SELECT topic, weight, updated_at
FROM topic_weights
WHERE weight != 1.0 OR updated_at > (SELECT MIN(created_at) FROM idea_feedback)
ORDER BY updated_at DESC;

-- 5. Simulate the UPDATE query for a recent feedback to see what would match
-- (You'll need to replace {idea_id} with an actual idea_id from feedback)
SELECT
    tw.topic,
    tw.weight as current_weight,
    kw as keyword_from_paper,
    CASE WHEN tw.topic = kw THEN 'MATCH' ELSE 'NO MATCH' END as match_status
FROM ideas i
JOIN papers p ON i.paper_id = p.id,
     UNNEST(p.keyword_hits) AS kw
LEFT JOIN topic_weights tw ON tw.topic = kw
WHERE i.id IN (SELECT idea_id FROM idea_feedback ORDER BY created_at DESC LIMIT 1);

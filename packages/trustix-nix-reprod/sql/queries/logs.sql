-- name: GetLog :one
SELECT * FROM log
WHERE log_id = ? LIMIT 1;

-- name: CreateLog :one
INSERT INTO log (log_id, tree_size) VALUES (?, 0) RETURNING *;
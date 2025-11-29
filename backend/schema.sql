-- Database creation SQL for mail-bot

CREATE TABLE user_tokens (
    id SERIAL PRIMARY KEY,
    email VARCHAR(256) UNIQUE NOT NULL,
    name VARCHAR(256),
    encrypted_payload TEXT NOT NULL,
    scopes VARCHAR(512),
    revoked BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE user_prompts (
    id SERIAL PRIMARY KEY,
    email VARCHAR(256) NOT NULL,
    prompt_type VARCHAR(64) NOT NULL,
    custom_prompt TEXT NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX idx_user_tokens_email ON user_tokens(email);
CREATE INDEX idx_user_prompts_email ON user_prompts(email);
CREATE INDEX idx_user_prompts_prompt_type ON user_prompts(prompt_type);

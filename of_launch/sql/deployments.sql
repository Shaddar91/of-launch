CREATE TABLE IF NOT EXISTS {deployments} (
    id INT AUTO_INCREMENT PRIMARY KEY,
    user VARCHAR(50) NULL,
    environment VARCHAR(255) NOT NULL,
    service_name VARCHAR(255) NOT NULL,
    image_tag VARCHAR(255) NOT NULL,
    deployment_type VARCHAR(50) DEFAULT 'frontend',
    status VARCHAR(50) DEFAULT 'triggered',
    artifact_version VARCHAR(255) DEFAULT NULL,
    deployment_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (user) REFERENCES {users} (username) ON DELETE SET NULL
)

CREATE TABLE IF NOT EXISTS access_points (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bssid TEXT NOT NULL UNIQUE,
    ssid TEXT DEFAULT '',
    channel INTEGER,
    frequency INTEGER,
    signal_dbm INTEGER,
    signal_min INTEGER,
    signal_max INTEGER,
    encryption TEXT,
    cipher TEXT,
    auth TEXT,
    wps INTEGER DEFAULT 0,
    vendor TEXT DEFAULT '',
    client_count INTEGER DEFAULT 0,
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    hidden INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS clients (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    mac TEXT NOT NULL UNIQUE,
    associated_bssid TEXT,
    signal_dbm INTEGER,
    vendor TEXT DEFAULT '',
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    last_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (associated_bssid) REFERENCES access_points(bssid)
);

CREATE TABLE IF NOT EXISTS probe_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    client_mac TEXT NOT NULL,
    ssid TEXT NOT NULL,
    signal_dbm INTEGER,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (client_mac) REFERENCES clients(mac)
);

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    tool TEXT NOT NULL,
    args TEXT,
    status TEXT DEFAULT 'pending',
    pid INTEGER,
    exit_code INTEGER,
    output_tail TEXT,
    result_file TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    started_at TIMESTAMP,
    completed_at TIMESTAMP
);

CREATE TABLE IF NOT EXISTS handshakes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    bssid TEXT NOT NULL,
    ssid TEXT,
    file_path TEXT NOT NULL,
    client_mac TEXT,
    four_way_complete INTEGER DEFAULT 0,
    captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS nmap_scans (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT,
    target TEXT NOT NULL,
    scan_type TEXT,
    result_xml TEXT,
    host_count INTEGER,
    open_ports_count INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (job_id) REFERENCES jobs(id)
);

CREATE TABLE IF NOT EXISTS sdr_recordings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    freq_start_hz INTEGER,
    freq_end_hz INTEGER,
    bin_size TEXT,
    file_path TEXT NOT NULL,
    duration_sec INTEGER,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE INDEX IF NOT EXISTS idx_ap_last_seen ON access_points(last_seen);
CREATE INDEX IF NOT EXISTS idx_clients_bssid ON clients(associated_bssid);
CREATE INDEX IF NOT EXISTS idx_probes_client ON probe_requests(client_mac);
CREATE INDEX IF NOT EXISTS idx_probes_ssid ON probe_requests(ssid);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
CREATE INDEX IF NOT EXISTS idx_jobs_created ON jobs(created_at);

-- MeshCore tables
CREATE TABLE IF NOT EXISTS mesh_contacts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL UNIQUE,
    name TEXT,
    public_key TEXT,
    latitude REAL,
    longitude REAL,
    battery_level INTEGER,
    snr REAL,
    rssi INTEGER,
    last_heard TIMESTAMP,
    first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mesh_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    direction TEXT NOT NULL,
    message_type TEXT NOT NULL,
    from_node_id TEXT,
    to_node_id TEXT,
    channel_id INTEGER,
    message TEXT NOT NULL,
    ack_received INTEGER DEFAULT 0,
    expected_ack TEXT,
    snr REAL,
    hop_count INTEGER,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mesh_telemetry (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_id TEXT NOT NULL,
    battery_level INTEGER,
    voltage REAL,
    temperature REAL,
    humidity REAL,
    latitude REAL,
    longitude REAL,
    altitude REAL,
    timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS mesh_device_state (
    key TEXT PRIMARY KEY,
    value TEXT,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_mesh_contacts_heard ON mesh_contacts(last_heard DESC);
CREATE INDEX IF NOT EXISTS idx_mesh_messages_ts ON mesh_messages(timestamp DESC);
CREATE INDEX IF NOT EXISTS idx_mesh_messages_from ON mesh_messages(from_node_id);
CREATE INDEX IF NOT EXISTS idx_mesh_telemetry_node ON mesh_telemetry(node_id, timestamp DESC);

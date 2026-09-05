import hashlib
from sqlalchemy.orm import Session
from ledger_guard.db.models import FileIngestionLog

def calculate_sha256(file_path: str) -> str:
    """
    Generate a SHA-256 cryptographic hash for the incoming file's bytes.
    Reads in chunks to avoid memory spikes with large files.
    """
    sha256_hash = hashlib.sha256()
    with open(file_path, "rb") as f:
        # Read and update hash string value in blocks of 4K
        for byte_block in iter(lambda: f.read(4096), b""):
            sha256_hash.update(byte_block)
    return sha256_hash.hexdigest()

def check_and_register_file(file_path: str, db: Session) -> bool:
    """
    Queries the database; if this hash already exists, returns False (drop file).
    If it's net-new, registers it as 'PROCESSING' and returns True.
    """
    file_hash = calculate_sha256(file_path)
    file_name = file_path.split('/')[-1]
    
    existing_log = db.query(FileIngestionLog).filter(FileIngestionLog.file_hash == file_hash).first()
    
    if existing_log:
        print(f"Idempotency Triggered: File {file_name} with hash {file_hash} has already been processed. Dropping.")
        return False
        
    # Net-new file, register it
    new_log = FileIngestionLog(file_name=file_name, file_hash=file_hash, status="PROCESSING")
    db.add(new_log)
    db.commit()
    print(f"Idempotency Passed: Registered new file {file_name} with hash {file_hash}.")
    
    return True

def mark_file_completed(file_hash: str, db: Session):
    log = db.query(FileIngestionLog).filter(FileIngestionLog.file_hash == file_hash).first()
    if log:
        log.status = "COMPLETED"
        db.commit()

def mark_file_failed(file_hash: str, db: Session):
    log = db.query(FileIngestionLog).filter(FileIngestionLog.file_hash == file_hash).first()
    if log:
        log.status = "FAILED"
        db.commit()

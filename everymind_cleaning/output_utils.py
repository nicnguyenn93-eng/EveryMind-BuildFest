"""Local output publication without depending on a particular privacy tool."""


def finalize_outputs(staged):
    """Roll back ordinary replacement failures across the staged output set."""
    backups, completed = {}, []
    try:
        for temporary, destination in staged:
            if destination.exists():
                backup = temporary.with_suffix(".backup")
                backup.write_bytes(destination.read_bytes())
                backups[destination] = backup
        for temporary, destination in staged:
            temporary.replace(destination)
            completed.append(destination)
    except OSError:
        for destination in reversed(completed):
            if destination in backups:
                backups[destination].replace(destination)
            else:
                destination.unlink(missing_ok=True)
        raise

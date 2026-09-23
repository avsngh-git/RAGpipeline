def validate_year_range(year_from: int, year_to: int) -> bool:
    if year_from <= year_to:
        return True
    else:
        return False

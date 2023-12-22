import datetime
import random
from astral import LocationInfo
from astral.sun import sun
#from datetime import datetime, timedelta

def random_time_between(start_str, end_str):
    # Konvertieren Sie die String-Zeiten in datetime.time-Objekte
    start = datetime.datetime.strptime(start_str, '%H:%M').time()
    end = datetime.datetime.strptime(end_str, '%H:%M').time()
    
    # Überprüfen Sie, ob die Startzeit vor der Endzeit liegt
    if start >= end:
        raise ValueError("Die Startzeit muss vor der Endzeit liegen.")
    
    # Zufällig auswählen, wie viele Sekunden vergangen sind
    start_seconds = start.hour * 3600 + start.minute * 60
    end_seconds = end.hour * 3600 + end.minute * 60
    seconds = random.randint(start_seconds, end_seconds)
    
    # Zum heutigen Datum die ausgewählten Sekunden hinzufügen
    random_datetime = datetime.timedelta(seconds=seconds)
    #print(datetime.timedelta(seconds=seconds))
    #print(start_seconds)
    #print(end_seconds)
    #print(seconds)
    return random_datetime

# Beispielverwendung:

#Wichtel Wach und Schlafzeit
#tt=random_time_between("06:00","10:00")
#print(tt.strftime('%H:%M'))
Wichtel_aktiv_wach = random_time_between("06:00","09:00")
Wichtel_aktiv_schlaf = random_time_between("18:00","23:00")
print(Wichtel_aktiv_wach)
print(Wichtel_aktiv_schlaf)
#print(tt.strftime('%H:%M'))

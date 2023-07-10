Documentation for SAC Red Stars Database Version 2.0

Dated July 7, 2008

by Steve Coe

stevecoe at cloudynights dot com

For as many years as we have been observing the sky, SAC members have enjoyed viewing stars with color.  These tints are subtle and demand training your eye to see them, but we consider it worthwhile so that you can start to see stars as something other than white.  Even with the naked eye some bright stars are ruddy in color; Antares and Betelgeuse are the most obvious examples.  Adding a telescope to the pursuit of color in stars means that many more stars can be seen in color.  Most often the colors viewed are mixtures of yellow, orange and red.

Several avid observers from years past have created a numeric scale for judging color in stars.  I will provide you with just one of these, from J.F.J. Schmidt, who was the head of the observatory in Athens, Greece for many years.  Using a 6 inch refractor he discussed the colors he saw as "0 is pure white, 4 is pure yellow, 6 is deep golden yellow, 8 is orange and 10 is pure red".  He said that he never gave any star a rating of 10.

The spectra of a star tells much about the chemistry, temperature and other physical conditions of the star.  The coolest "normal" stars are in spectral types K and M.  These stars often appear medium yellow to light orange to many observers.  The carbon stars are stars that are surrounded by a cloud of carbon soot.  This cloud filters out most of the blue light from the surface of the star and makes them much redder to an observer.  These stars are given the obvious designation "C" and the less obvious "N".  

SAC members starting this pursuit of tinted stars with a listing of red stars we distributed as part of "Potporri", a set of lists included in the zip file with the SAC Deep Sky Database.  That listing contains 70 stars with very simple information on each.  This list is a greatly expanded version of that simple beginning.  As always, if you know any of the data that would fill in gaps in this database, please get in touch.

Bill Anderson helped with the creation of the database format and checked for accuracy.

Steve Coe wrote the file you are reading and searched a variety of sources for the information that was added to this database.

Alister Ling helped with checking for accuracy and helped with this read me file.

Brian Skiff provided several excellent sources of tinted stars.

So, here is the information on what is in each field of this database:

Field 1; 13 characters 
Common Name--the name you would most often use to refer to this star.  It is often difficult to determine exactly which of several designations is the most common.  Here is an explanation of the abbreviations used in this field and in the "Other Names" field.

Variable Star Designation using Letters, such as R Leo or SS Cyg.  Most of the tinted stars in the sky are variable and so this is one of the most common of the designations.  Once the letter pairs are used up, then the variables within a constellation start using a numbered "V" designation, such as V1942 Sgr.

Bayer designations use the Greek letters, they are spelled out, so that Antares is Alpha Sco.

BD for Bonner Durchmusterung, a catalog that is now over 150 years old and covers the northern sky to magnitude 9.  

CCCS for Catalog of Cool Carbon Stars by Stephenson.  A listing of carbon stars.

CD for Cape Durchmusterung, an extension of the BD, completed at the Cape Observatory in South Africa.

HD is the Henry Draper catalog.

SAO is the Smithsonian Astrophysical Observatory catalog, a catalog of stars to 9th magnitude.

STF for F.G.W. Struve.  Several of the most famous double stars that contain red or orange members are included in this tinted star database.

TYC is the Tycho catalog, taken from the Tycho satellite.


Field 2; 37 characters

Other Names, this field contains other designations.


Field 3; 3 characters 
Constellation, the constellation abbreviations in three letters.

ANDROMEDA           AND                 LACERTA             LAC
ANTLIA              ANT                 LEO                 LEO
APUS                APS                 LEO MINOR           LMI
AQUARIUS            AQR                 LEPUS               LEP
AQUILA              AQL                 LIBRA               LIB
ARA                 ARA                 LUPUS               LUP
ARIES               ARI                 LYNX                LYN
AURIGA              AUR                 LYRA                LYR
BOOTES              BOO                 MENSA               MEN
CAELUM              CAE                 MICROSCOPIUM        MIC
CAMELOPARDALIS      CAM                 MONOCEROS           MON
CANCER              CNC                 MUSCA               MUS
CANES VENATICI      CVN                 NORMA               NOR
CANIS MAJOR         CMA                 OCTANS              OCT
CANIS MINOR         CMI                 OPHIUCHUS           OPH
CAPRICORNUS         CAP                 ORION               ORI
CARINA              CAR                 PAVO                PAV
CASSIOPEIA          CAS                 PEGASUS             PEG
CENTAURUS           CEN                 PERSEUS             PER
CEPHEUS             CEP                 PHOENIX             PHE
CETUS               CET                 PICTOR              PIC
CHAMAELEON          CHA                 PISCES              PSC
CIRCINUS            CIR                 PISCES AUSTRINUS    PSA
COLUMBA             COL                 PUPPIS              PUP
COMA BERENICES      COM                 PYXIS               PYX
CORONA AUSTRALIS    CRA                 RETICULUM           RET
CORONA BOREALIS     CRB                 SAGITTA             SGE
CORVUS              CRV                 SAGITTARIUS         SGR
CRATER              CRT                 SCORPIUS            SCO
CRUX                CRU                 SCULPTOR            SCL
CYGNUS              CYG                 SCUTUM              SCT
DELPHINUS           DEL                 SERPENS             SER
DORADO              DOR                 SEXTANS             SEX
DRACO               DRA                 TAURUS              TAU
EQUULEUS            EQU                 TELESCOPIUM         TEL
ERIDANUS            ERI                 TRIANGULUM AUSTRALE TRA
FORNAX              FOR                 TRIANGULUM          TRI
GEMINI              GEM                 TUCANA              TUC
GRUS                GRU                 URSA MAJOR          UMA
HERCULES            HER                 URSA MINOR          UMI
HOROLOGIUM          HOR                 VELA                VEL
HYDRA               HYA                 VIRGO               VIR
HYDRUS              HYI                 VOLANS              VOL
INDUS               IND                 VULPECULA           VUL


Field 4; 7 characters
RAJ2K  
Right Ascension of the object in equinox 2000.0 coordinates.  The RA is in the form  XX XX.X, such as 14 34.8 or 05 04.7.  Leading zeros are present so that a sort of the data will be numerically correct.


Field 5; 6 characters     
DECJ2K   
Declination of the object in equinox 2000.0 coordinates.  The DEC is in the form  +/-XX XX, such as +48 10 or -88 04.  Use the sign and leading zeros.  The declination is given in degrees and minutes.


Field 6; 4 Characters
VMAG
Magnitude in visual wavelengths to the nearest tenth in the form XX.X, such as 10.3.  


Field 7; 4 characters
B-V
The "Bee minus Vee" value is a subtraction of the magnitude in the blue region with the magnitude in the visual range.  It is a numeric calculation of how red the star will appear.  The higher this value, the redder the star.  A star with a negative B-V will be blue.  An example would be Spica, its B-V value is -0.25.  Our Sun is light yellow and it has a B-V of +0.65.  A light orange star like Antares has a B-V of +1.8.  R Leporis (Hind's Crimson Star) is a famous red carbon star and its B-V is +5.5.  Since this is a list of reddish stars, there are no negative B-V values for any of these stars, so I made it easy on myself and there are no plus signs in this field.   


Field 8; 6 characters
Spectral Type
A spectoscope is a device that allows an astronomer to capture the light from a star and spread it out so that much information about the star can be determined.  The letters associated with the spectra of normal stars are O,B,A,F,G,K,M.  That sequence is from the hot O and B stars to the cool K and M types.  Within each letter is a sequence of numbers from 0 (zero) to 9 that go from hottest to coolest within that letter value.  So, a K2 star is hotter than a K9 star.

The carbon stars are going to be the reddest stars in the sky because of a layer of soot that surrounds the star.  A variety of carbon and carbon molecules are dredged up from the star's interior and creates a dark haze layer that blue light cannot penetrate.  Because the spectra of these stars is different from stars on the main sequence they get their own spectral type, obviously Type C.

Other researchers added Class R to include the G and K giant stars and then Class N to combine the K and M cool giant stars.

Stars will appear orange or reddish in the eyepiece of your telescope for two reasons:  first, they are cool stars.  Just like heating a piece of steel and watching the metal turn from orange to yellow to blue-white, the coolest stars are orange and red in color.  The second reason stars turn red is that the carbon soot cloud that surrounds the star will filter out the blue light from the surface of the star and so it appears orange or red.  The reddest stars are going to be carbon stars, look for a "C" in the spectral type and the usual number sequence for temperature.  Also, R and N stars can show color, particularly if they are very cool stars, such as V Aql which is an N6 star and has a B-V of 4.19.  This star appears dark orange to me.

The final spectral class is "S", this stands for "slow", which means that the neutrons in these starts are moving slow enough to form zirconium and barium.  These stars are cool and there is some carbon in the atmospheres of these stars also, so they are reddened.

There is one more level of complication, "p" means peculiar lines appear in the spectrum, "e" means emission lines.  I don't have the foggiest idea what these would mean to a visual observer.  If you figure it out, let me know.   
    

Field 9; 60 characters
Notes
There is information in the notes about the location and variability of the star.  If there is another deep sky object nearby, information about that is included.  If the star is part of a multiple star then information on magnitude, separation and position angle of the companion star is here.













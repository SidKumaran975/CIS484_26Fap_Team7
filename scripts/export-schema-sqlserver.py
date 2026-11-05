"""Generate the static SSMS schema from ERD (Page 1) (10).png, not the app DB."""
from pathlib import Path

# Column order matches the supplied diagram. Types/lengths are implementation choices.
T = {
'USER': [('UserID','INT'),('UserName','NVARCHAR(200)'),('PasswordHash','NVARCHAR(500)'),('Email','NVARCHAR(320)'),('FirstName','NVARCHAR(100)'),('LastName','NVARCHAR(100)')],
'AUTH_SESSION': [('TokenHash','NVARCHAR(200)'),('UserID','INT'),('ExpiresAt','DATETIME2')],
'STUDENT': [('StudentID','INT'),('EnrollmentDate','DATE'),('AcademicLevel','NVARCHAR(100)'),('Major','NVARCHAR(200)'),('EnrollmentStatus','NVARCHAR(100)')],
'INSTRUCTOR': [('InstructorID','INT'),('DepartmentID','INT'),('FaceImagePath','NVARCHAR(2048)'),('VoiceSamplePath','NVARCHAR(2048)')],
'DEPARTMENT': [('DepartmentID','INT'),('DepartmentName','NVARCHAR(200)'),('DepartmentCode','NVARCHAR(50)')],
'STUDENT_SEC': [('StudentID','INT'),('SectionID','INT')],
'SECTION': [('SectionID','INT'),('InstructorID','INT'),('CourseID','INT'),('SectionNumber','NVARCHAR(50)')],
'COURSE': [('CourseID','INT'),('DepartmentID','INT'),('CourseCode','NVARCHAR(50)'),('CourseName','NVARCHAR(200)'),('CourseDescription','NVARCHAR(MAX)')],
'COURSE_DOC': [('DocumentID','INT'),('CourseID','INT'),('DocumentName','NVARCHAR(255)'),('FilePath','NVARCHAR(2048)'),('FileType','NVARCHAR(50)'),('UploadedAt','DATETIME2'),('ProcessingStatus','NVARCHAR(100)')],
'DOC_CHUNKS': [('DocChunkID','INT'),('DocumentID','INT'),('Idx','INT'),('Text','NVARCHAR(MAX)')],
'EXAM': [('ExamID','INT'),('CourseID','INT'),('ExamTitle','NVARCHAR(255)'),('ExamDescription','NVARCHAR(MAX)'),('ExamStatus','NVARCHAR(100)'),('TimeLimit','INT'),('CreatedAt','DATETIME2'),('PublishedAt','DATETIME2'),('PromptInstructions','NVARCHAR(MAX)')],
'EXAM_DOC': [('ExamID','INT'),('DocumentID','INT')],
'QUEST_BANK': [('BankID','INT'),('ExamID','INT'),('DocSource','NVARCHAR(MAX)')],
'QUEST_ESS': [('QuestionID','INT'),('BankID','INT'),('QuestionText','NVARCHAR(MAX)')],
'SESSION': [('SessionID','INT'),('StudentID','INT'),('InstructorID','INT'),('ExamID','INT'),('StartTime','DATETIME2'),('EndTime','DATETIME2'),('SessionStatus','NVARCHAR(100)')],
'INTERACTION': [('InteractionID','INT'),('SessionID','INT'),('QuestionID','INT'),('PickedTransID','INT'),('Evaluation','NVARCHAR(MAX)'),('ActualQuestionTxt','NVARCHAR(MAX)'),('ActualQuestionVid','NVARCHAR(2048)'),('SequenceNumber','INT'),('StartTime','DATETIME2'),('QuestionEndTime','DATETIME2'),('EndTime','DATETIME2'),('NextAction','NVARCHAR(100)')],
'RECORDING': [('RecordingID','INT'),('SessionID','INT'),('StartTime','DATETIME2'),('EndTime','DATETIME2'),('RecordingPath','NVARCHAR(2048)')],
'CLIP_RESP': [('RespClip','INT'),('InteractionID','INT'),('Recording','INT'),('AudioFilePath','NVARCHAR(2048)'),('StartTime','DATETIME2'),('EndTime','DATETIME2'),('FileFormat','NVARCHAR(50)')],
'CLIP_TRANS': [('TranscriptID','INT'),('RespClipID','INT'),('TranscriptText','NVARCHAR(MAX)')],
}
# ERD uses RespClip as the CLIP_RESP PK and Recording as its recording FK.
PK = {n:[cols[0][0]] for n,cols in T.items()}
PK['STUDENT_SEC']=['StudentID','SectionID']
PK['EXAM_DOC']=['ExamID','DocumentID']
F = [
('AUTH_SESSION','UserID','USER','UserID'),('STUDENT','StudentID','USER','UserID'),
('INSTRUCTOR','InstructorID','USER','UserID'),('INSTRUCTOR','DepartmentID','DEPARTMENT','DepartmentID'),
('STUDENT_SEC','StudentID','STUDENT','StudentID'),('STUDENT_SEC','SectionID','SECTION','SectionID'),
('SECTION','InstructorID','INSTRUCTOR','InstructorID'),('SECTION','CourseID','COURSE','CourseID'),
('COURSE','DepartmentID','DEPARTMENT','DepartmentID'),('COURSE_DOC','CourseID','COURSE','CourseID'),
('DOC_CHUNKS','DocumentID','COURSE_DOC','DocumentID'),('EXAM','CourseID','COURSE','CourseID'),
('EXAM_DOC','ExamID','EXAM','ExamID'),('EXAM_DOC','DocumentID','COURSE_DOC','DocumentID'),
('QUEST_BANK','ExamID','EXAM','ExamID'),('QUEST_ESS','BankID','QUEST_BANK','BankID'),
('SESSION','StudentID','STUDENT','StudentID'),('SESSION','InstructorID','INSTRUCTOR','InstructorID'),
('SESSION','ExamID','EXAM','ExamID'),('INTERACTION','SessionID','SESSION','SessionID'),
('INTERACTION','QuestionID','QUEST_ESS','QuestionID'),('INTERACTION','PickedTransID','CLIP_TRANS','TranscriptID'),
('RECORDING','SessionID','SESSION','SessionID'),('CLIP_RESP','InteractionID','INTERACTION','InteractionID'),
('CLIP_RESP','Recording','RECORDING','RecordingID'),('CLIP_TRANS','RespClipID','CLIP_RESP','RespClip'),
]
nullable_fk = {('QUEST_ESS','BankID'), ('INTERACTION','PickedTransID')}
q=lambda s:'['+s+']'
lines=[
'-- Static inspection schema matching ERD (Page 1) (10).png: 19 tables.',
'-- Types/lengths are chosen because the diagram does not specify them.',
'-- Diagram spellings retained: CLIP_RESP.RespClip and CLIP_RESP.Recording.',
'-- CLIP_TRANS.RespClipID references CLIP_RESP.RespClip.',
'-- Optional PickedTransID permits creating interactions before their transcripts.',
'-- Non-key attributes are nullable; foreign keys use NO ACTION.',
'-- No app data, extra application tables, or live synchronization.',
'USE [master];','GO',
"IF DB_ID(N'OralExamERD') IS NULL EXEC(N'CREATE DATABASE [OralExamERD]');",'GO',
'USE [OralExamERD];','GO','SET XACT_ABORT ON;','BEGIN TRANSACTION;','']
required={(n,c) for n,ks in PK.items() for c in ks} | {(n,c) for n,c,_,_ in F if (n,c) not in nullable_fk}
for n,cols in T.items():
 d=['    '+q(c)+' '+typ+(' NOT NULL' if (n,c) in required else ' NULL') for c,typ in cols]
 d.append('    CONSTRAINT '+q('PK_'+n)+' PRIMARY KEY ('+', '.join(map(q,PK[n]))+')')
 if n=='CLIP_RESP':
  d.append('    CONSTRAINT [UQ_CLIP_RESP_InteractionID] UNIQUE ([InteractionID])')
 lines.append('CREATE TABLE [dbo].'+q(n)+' (\n'+',\n'.join(d)+'\n);\n')
for n,c,ref,col in F:
 assert c in dict(T[n]) and col in dict(T[ref])
 assert dict(T[n])[c]==dict(T[ref])[col]
 lines.append('ALTER TABLE [dbo].'+q(n)+' ADD CONSTRAINT '+q('FK_'+n+'_'+c)+' FOREIGN KEY ('+q(c)+') REFERENCES [dbo].'+q(ref)+' ('+q(col)+');')
lines+=['','COMMIT TRANSACTION;','GO']
root=Path(__file__).resolve().parents[1]
(root/'database/schema-snapshot-sqlserver.sql').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print(f'Generated {len(T)} tables, {sum(map(len,T.values()))} columns, {len(F)} foreign keys.')

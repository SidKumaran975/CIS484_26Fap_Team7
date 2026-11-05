-- Static inspection schema matching ERD (Page 1) (10).png: 19 tables.
-- Types/lengths are chosen because the diagram does not specify them.
-- Diagram spellings retained: CLIP_RESP.RespClip and CLIP_RESP.Recording.
-- CLIP_TRANS.RespClipID references CLIP_RESP.RespClip.
-- Optional PickedTransID permits creating interactions before their transcripts.
-- Non-key attributes are nullable; foreign keys use NO ACTION.
-- No app data, extra application tables, or live synchronization.
USE [master];
GO
IF DB_ID(N'OralExamERD') IS NULL EXEC(N'CREATE DATABASE [OralExamERD]');
GO
USE [OralExamERD];
GO
SET XACT_ABORT ON;
BEGIN TRANSACTION;

CREATE TABLE [dbo].[USER] (
    [UserID] INT NOT NULL,
    [UserName] NVARCHAR(200) NULL,
    [PasswordHash] NVARCHAR(500) NULL,
    [Email] NVARCHAR(320) NULL,
    [FirstName] NVARCHAR(100) NULL,
    [LastName] NVARCHAR(100) NULL,
    CONSTRAINT [PK_USER] PRIMARY KEY ([UserID])
);

CREATE TABLE [dbo].[AUTH_SESSION] (
    [TokenHash] NVARCHAR(200) NOT NULL,
    [UserID] INT NOT NULL,
    [ExpiresAt] DATETIME2 NULL,
    CONSTRAINT [PK_AUTH_SESSION] PRIMARY KEY ([TokenHash])
);

CREATE TABLE [dbo].[STUDENT] (
    [StudentID] INT NOT NULL,
    [EnrollmentDate] DATE NULL,
    [AcademicLevel] NVARCHAR(100) NULL,
    [Major] NVARCHAR(200) NULL,
    [EnrollmentStatus] NVARCHAR(100) NULL,
    CONSTRAINT [PK_STUDENT] PRIMARY KEY ([StudentID])
);

CREATE TABLE [dbo].[INSTRUCTOR] (
    [InstructorID] INT NOT NULL,
    [DepartmentID] INT NOT NULL,
    [FaceImagePath] NVARCHAR(2048) NULL,
    [VoiceSamplePath] NVARCHAR(2048) NULL,
    CONSTRAINT [PK_INSTRUCTOR] PRIMARY KEY ([InstructorID])
);

CREATE TABLE [dbo].[DEPARTMENT] (
    [DepartmentID] INT NOT NULL,
    [DepartmentName] NVARCHAR(200) NULL,
    [DepartmentCode] NVARCHAR(50) NULL,
    CONSTRAINT [PK_DEPARTMENT] PRIMARY KEY ([DepartmentID])
);

CREATE TABLE [dbo].[STUDENT_SEC] (
    [StudentID] INT NOT NULL,
    [SectionID] INT NOT NULL,
    CONSTRAINT [PK_STUDENT_SEC] PRIMARY KEY ([StudentID], [SectionID])
);

CREATE TABLE [dbo].[SECTION] (
    [SectionID] INT NOT NULL,
    [InstructorID] INT NOT NULL,
    [CourseID] INT NOT NULL,
    [SectionNumber] NVARCHAR(50) NULL,
    CONSTRAINT [PK_SECTION] PRIMARY KEY ([SectionID])
);

CREATE TABLE [dbo].[COURSE] (
    [CourseID] INT NOT NULL,
    [DepartmentID] INT NOT NULL,
    [CourseCode] NVARCHAR(50) NULL,
    [CourseName] NVARCHAR(200) NULL,
    [CourseDescription] NVARCHAR(MAX) NULL,
    CONSTRAINT [PK_COURSE] PRIMARY KEY ([CourseID])
);

CREATE TABLE [dbo].[COURSE_DOC] (
    [DocumentID] INT NOT NULL,
    [CourseID] INT NOT NULL,
    [DocumentName] NVARCHAR(255) NULL,
    [FilePath] NVARCHAR(2048) NULL,
    [FileType] NVARCHAR(50) NULL,
    [UploadedAt] DATETIME2 NULL,
    [ProcessingStatus] NVARCHAR(100) NULL,
    CONSTRAINT [PK_COURSE_DOC] PRIMARY KEY ([DocumentID])
);

CREATE TABLE [dbo].[DOC_CHUNKS] (
    [DocChunkID] INT NOT NULL,
    [DocumentID] INT NOT NULL,
    [Idx] INT NULL,
    [Text] NVARCHAR(MAX) NULL,
    CONSTRAINT [PK_DOC_CHUNKS] PRIMARY KEY ([DocChunkID])
);

CREATE TABLE [dbo].[EXAM] (
    [ExamID] INT NOT NULL,
    [CourseID] INT NOT NULL,
    [ExamTitle] NVARCHAR(255) NULL,
    [ExamDescription] NVARCHAR(MAX) NULL,
    [ExamStatus] NVARCHAR(100) NULL,
    [TimeLimit] INT NULL,
    [CreatedAt] DATETIME2 NULL,
    [PublishedAt] DATETIME2 NULL,
    [PromptInstructions] NVARCHAR(MAX) NULL,
    CONSTRAINT [PK_EXAM] PRIMARY KEY ([ExamID])
);

CREATE TABLE [dbo].[EXAM_DOC] (
    [ExamID] INT NOT NULL,
    [DocumentID] INT NOT NULL,
    CONSTRAINT [PK_EXAM_DOC] PRIMARY KEY ([ExamID], [DocumentID])
);

CREATE TABLE [dbo].[QUEST_BANK] (
    [BankID] INT NOT NULL,
    [ExamID] INT NOT NULL,
    [DocSource] NVARCHAR(MAX) NULL,
    CONSTRAINT [PK_QUEST_BANK] PRIMARY KEY ([BankID])
);

CREATE TABLE [dbo].[QUEST_ESS] (
    [QuestionID] INT NOT NULL,
    [BankID] INT NULL,
    [QuestionText] NVARCHAR(MAX) NULL,
    CONSTRAINT [PK_QUEST_ESS] PRIMARY KEY ([QuestionID])
);

CREATE TABLE [dbo].[SESSION] (
    [SessionID] INT NOT NULL,
    [StudentID] INT NOT NULL,
    [InstructorID] INT NOT NULL,
    [ExamID] INT NOT NULL,
    [StartTime] DATETIME2 NULL,
    [EndTime] DATETIME2 NULL,
    [SessionStatus] NVARCHAR(100) NULL,
    CONSTRAINT [PK_SESSION] PRIMARY KEY ([SessionID])
);

CREATE TABLE [dbo].[INTERACTION] (
    [InteractionID] INT NOT NULL,
    [SessionID] INT NOT NULL,
    [QuestionID] INT NOT NULL,
    [PickedTransID] INT NULL,
    [Evaluation] NVARCHAR(MAX) NULL,
    [ActualQuestionTxt] NVARCHAR(MAX) NULL,
    [ActualQuestionVid] NVARCHAR(2048) NULL,
    [SequenceNumber] INT NULL,
    [StartTime] DATETIME2 NULL,
    [QuestionEndTime] DATETIME2 NULL,
    [EndTime] DATETIME2 NULL,
    [NextAction] NVARCHAR(100) NULL,
    CONSTRAINT [PK_INTERACTION] PRIMARY KEY ([InteractionID])
);

CREATE TABLE [dbo].[RECORDING] (
    [RecordingID] INT NOT NULL,
    [SessionID] INT NOT NULL,
    [StartTime] DATETIME2 NULL,
    [EndTime] DATETIME2 NULL,
    [RecordingPath] NVARCHAR(2048) NULL,
    CONSTRAINT [PK_RECORDING] PRIMARY KEY ([RecordingID])
);

CREATE TABLE [dbo].[CLIP_RESP] (
    [RespClip] INT NOT NULL,
    [InteractionID] INT NOT NULL,
    [Recording] INT NOT NULL,
    [AudioFilePath] NVARCHAR(2048) NULL,
    [StartTime] DATETIME2 NULL,
    [EndTime] DATETIME2 NULL,
    [FileFormat] NVARCHAR(50) NULL,
    CONSTRAINT [PK_CLIP_RESP] PRIMARY KEY ([RespClip]),
    CONSTRAINT [UQ_CLIP_RESP_InteractionID] UNIQUE ([InteractionID])
);

CREATE TABLE [dbo].[CLIP_TRANS] (
    [TranscriptID] INT NOT NULL,
    [RespClipID] INT NOT NULL,
    [TranscriptText] NVARCHAR(MAX) NULL,
    CONSTRAINT [PK_CLIP_TRANS] PRIMARY KEY ([TranscriptID])
);

ALTER TABLE [dbo].[AUTH_SESSION] ADD CONSTRAINT [FK_AUTH_SESSION_UserID] FOREIGN KEY ([UserID]) REFERENCES [dbo].[USER] ([UserID]);
ALTER TABLE [dbo].[STUDENT] ADD CONSTRAINT [FK_STUDENT_StudentID] FOREIGN KEY ([StudentID]) REFERENCES [dbo].[USER] ([UserID]);
ALTER TABLE [dbo].[INSTRUCTOR] ADD CONSTRAINT [FK_INSTRUCTOR_InstructorID] FOREIGN KEY ([InstructorID]) REFERENCES [dbo].[USER] ([UserID]);
ALTER TABLE [dbo].[INSTRUCTOR] ADD CONSTRAINT [FK_INSTRUCTOR_DepartmentID] FOREIGN KEY ([DepartmentID]) REFERENCES [dbo].[DEPARTMENT] ([DepartmentID]);
ALTER TABLE [dbo].[STUDENT_SEC] ADD CONSTRAINT [FK_STUDENT_SEC_StudentID] FOREIGN KEY ([StudentID]) REFERENCES [dbo].[STUDENT] ([StudentID]);
ALTER TABLE [dbo].[STUDENT_SEC] ADD CONSTRAINT [FK_STUDENT_SEC_SectionID] FOREIGN KEY ([SectionID]) REFERENCES [dbo].[SECTION] ([SectionID]);
ALTER TABLE [dbo].[SECTION] ADD CONSTRAINT [FK_SECTION_InstructorID] FOREIGN KEY ([InstructorID]) REFERENCES [dbo].[INSTRUCTOR] ([InstructorID]);
ALTER TABLE [dbo].[SECTION] ADD CONSTRAINT [FK_SECTION_CourseID] FOREIGN KEY ([CourseID]) REFERENCES [dbo].[COURSE] ([CourseID]);
ALTER TABLE [dbo].[COURSE] ADD CONSTRAINT [FK_COURSE_DepartmentID] FOREIGN KEY ([DepartmentID]) REFERENCES [dbo].[DEPARTMENT] ([DepartmentID]);
ALTER TABLE [dbo].[COURSE_DOC] ADD CONSTRAINT [FK_COURSE_DOC_CourseID] FOREIGN KEY ([CourseID]) REFERENCES [dbo].[COURSE] ([CourseID]);
ALTER TABLE [dbo].[DOC_CHUNKS] ADD CONSTRAINT [FK_DOC_CHUNKS_DocumentID] FOREIGN KEY ([DocumentID]) REFERENCES [dbo].[COURSE_DOC] ([DocumentID]);
ALTER TABLE [dbo].[EXAM] ADD CONSTRAINT [FK_EXAM_CourseID] FOREIGN KEY ([CourseID]) REFERENCES [dbo].[COURSE] ([CourseID]);
ALTER TABLE [dbo].[EXAM_DOC] ADD CONSTRAINT [FK_EXAM_DOC_ExamID] FOREIGN KEY ([ExamID]) REFERENCES [dbo].[EXAM] ([ExamID]);
ALTER TABLE [dbo].[EXAM_DOC] ADD CONSTRAINT [FK_EXAM_DOC_DocumentID] FOREIGN KEY ([DocumentID]) REFERENCES [dbo].[COURSE_DOC] ([DocumentID]);
ALTER TABLE [dbo].[QUEST_BANK] ADD CONSTRAINT [FK_QUEST_BANK_ExamID] FOREIGN KEY ([ExamID]) REFERENCES [dbo].[EXAM] ([ExamID]);
ALTER TABLE [dbo].[QUEST_ESS] ADD CONSTRAINT [FK_QUEST_ESS_BankID] FOREIGN KEY ([BankID]) REFERENCES [dbo].[QUEST_BANK] ([BankID]);
ALTER TABLE [dbo].[SESSION] ADD CONSTRAINT [FK_SESSION_StudentID] FOREIGN KEY ([StudentID]) REFERENCES [dbo].[STUDENT] ([StudentID]);
ALTER TABLE [dbo].[SESSION] ADD CONSTRAINT [FK_SESSION_InstructorID] FOREIGN KEY ([InstructorID]) REFERENCES [dbo].[INSTRUCTOR] ([InstructorID]);
ALTER TABLE [dbo].[SESSION] ADD CONSTRAINT [FK_SESSION_ExamID] FOREIGN KEY ([ExamID]) REFERENCES [dbo].[EXAM] ([ExamID]);
ALTER TABLE [dbo].[INTERACTION] ADD CONSTRAINT [FK_INTERACTION_SessionID] FOREIGN KEY ([SessionID]) REFERENCES [dbo].[SESSION] ([SessionID]);
ALTER TABLE [dbo].[INTERACTION] ADD CONSTRAINT [FK_INTERACTION_QuestionID] FOREIGN KEY ([QuestionID]) REFERENCES [dbo].[QUEST_ESS] ([QuestionID]);
ALTER TABLE [dbo].[INTERACTION] ADD CONSTRAINT [FK_INTERACTION_PickedTransID] FOREIGN KEY ([PickedTransID]) REFERENCES [dbo].[CLIP_TRANS] ([TranscriptID]);
ALTER TABLE [dbo].[RECORDING] ADD CONSTRAINT [FK_RECORDING_SessionID] FOREIGN KEY ([SessionID]) REFERENCES [dbo].[SESSION] ([SessionID]);
ALTER TABLE [dbo].[CLIP_RESP] ADD CONSTRAINT [FK_CLIP_RESP_InteractionID] FOREIGN KEY ([InteractionID]) REFERENCES [dbo].[INTERACTION] ([InteractionID]);
ALTER TABLE [dbo].[CLIP_RESP] ADD CONSTRAINT [FK_CLIP_RESP_Recording] FOREIGN KEY ([Recording]) REFERENCES [dbo].[RECORDING] ([RecordingID]);
ALTER TABLE [dbo].[CLIP_TRANS] ADD CONSTRAINT [FK_CLIP_TRANS_RespClipID] FOREIGN KEY ([RespClipID]) REFERENCES [dbo].[CLIP_RESP] ([RespClip]);

COMMIT TRANSACTION;
GO

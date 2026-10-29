BEGIN TRANSACTION;
CREATE TABLE AUTH_SESSION (
 TokenHash TEXT PRIMARY KEY, UserID INTEGER NOT NULL REFERENCES "USER" ON DELETE CASCADE, ExpiresAt REAL NOT NULL);
CREATE TABLE AVATAR (
 AvatarID TEXT PRIMARY KEY, ProfessorID INTEGER NOT NULL REFERENCES PROFESSOR,
 FaceImagePath TEXT, VoiceSamplePath TEXT, MediaVersion TEXT NOT NULL,
 UpdatedAt TEXT NOT NULL, IsCurrent INTEGER NOT NULL DEFAULT 1 CHECK(IsCurrent IN (0,1)),
 UNIQUE(ProfessorID,MediaVersion));
CREATE TABLE COURSE (
 CourseID TEXT PRIMARY KEY, ProfessorID INTEGER NOT NULL REFERENCES PROFESSOR,
 DepartmentID TEXT REFERENCES DEPARTMENT, CourseCode TEXT NOT NULL,
 CourseName TEXT NOT NULL, CourseDescription TEXT, Term TEXT, CreatedAt TEXT);
CREATE TABLE COURSE_DOC (
 DocumentID TEXT PRIMARY KEY, CourseID TEXT REFERENCES COURSE ON DELETE CASCADE,
 ProfessorID INTEGER REFERENCES PROFESSOR, DocumentName TEXT, FilePath TEXT,
 FileType TEXT, UploadedAt TEXT, ProcessingStatus TEXT DEFAULT 'processed',
 Characters INTEGER, FileSize INTEGER, RelativePath TEXT);
CREATE TABLE DEPARTMENT (
 DepartmentID TEXT PRIMARY KEY, DepartmentName TEXT NOT NULL, DepartmentCode TEXT UNIQUE);
CREATE TABLE DOC_CHUNKS (
 DocChunkID INTEGER PRIMARY KEY AUTOINCREMENT, DocumentID TEXT REFERENCES COURSE_DOC ON DELETE CASCADE,
 Idx INTEGER, Text TEXT, UNIQUE(DocumentID,Idx));
CREATE TABLE EVALUATION (
 EvaluationID TEXT PRIMARY KEY, ResponseID TEXT UNIQUE NOT NULL REFERENCES RESPONSE ON DELETE CASCADE,
 Rating REAL, Feedback TEXT, EvaluationJSON TEXT NOT NULL);
CREATE TABLE EXAM (
 ExamID TEXT PRIMARY KEY, CourseID TEXT REFERENCES COURSE ON DELETE SET NULL,
 ExamTitle TEXT, ExamDescription TEXT, ExamStatus TEXT, TimeLimit INTEGER,
 CreatedAt TEXT, PublishedAt TEXT, PromptInstructions TEXT, SettingsJSON TEXT,
 LegacyCourse TEXT, ProfessorID INTEGER REFERENCES PROFESSOR, MediaVersion TEXT,
 AvatarID TEXT REFERENCES AVATAR, DeletedAt TEXT);
CREATE TABLE EXAM_DOC (
 ExamID TEXT REFERENCES EXAM ON DELETE CASCADE,
 DocumentID TEXT REFERENCES COURSE_DOC ON DELETE CASCADE, PRIMARY KEY(ExamID,DocumentID));
CREATE TABLE EXAM_PUBLICATION (
 ExamID TEXT PRIMARY KEY REFERENCES EXAM ON DELETE CASCADE,
 PublishedAt TEXT NOT NULL, PayloadJSON TEXT NOT NULL CHECK(json_valid(PayloadJSON)));
CREATE TABLE INTERACTION (
 InteractionID TEXT PRIMARY KEY, SessionID TEXT NOT NULL REFERENCES "SESSION" ON DELETE CASCADE,
 QuestionID TEXT NOT NULL REFERENCES QUESTION_BANK, ActualQuestion TEXT NOT NULL,
 SequenceNumber INTEGER NOT NULL, AskedAt TEXT NOT NULL, NextAction TEXT NOT NULL,
 NextPrompt TEXT NOT NULL DEFAULT '', RetrievedJSON TEXT NOT NULL DEFAULT '[]',
 UNIQUE(SessionID,SequenceNumber));
CREATE TABLE PROFESSOR (
 ProfessorID INTEGER PRIMARY KEY REFERENCES "USER" ON DELETE CASCADE,
 UserID INTEGER UNIQUE NOT NULL REFERENCES "USER" ON DELETE CASCADE,
 JheID TEXT, FirstName TEXT, LastName TEXT, Email TEXT, CHECK(ProfessorID=UserID));
CREATE TABLE PROF_DEPART (
 ProfessorID INTEGER REFERENCES PROFESSOR ON DELETE CASCADE,
 DepartmentID TEXT REFERENCES DEPARTMENT ON DELETE CASCADE, PRIMARY KEY(ProfessorID,DepartmentID));
CREATE TABLE QUESTION_BANK (
 QuestionID TEXT PRIMARY KEY, ExamID TEXT REFERENCES EXAM ON DELETE CASCADE,
 ExternalQuestionID TEXT NOT NULL, QuestionText TEXT NOT NULL, QuestionSource TEXT,
 SequenceNumber INTEGER NOT NULL, QuestionData TEXT NOT NULL,
 IsActive INTEGER NOT NULL DEFAULT 1 CHECK(IsActive IN (0,1)),
 UNIQUE(ExamID,ExternalQuestionID));
CREATE TABLE RESPONSE (
 ResponseID TEXT PRIMARY KEY, InteractionID TEXT NOT NULL UNIQUE REFERENCES INTERACTION ON DELETE CASCADE,
 AnsweredAt TEXT NOT NULL);
CREATE TABLE RESP_REC (
 RecordingID TEXT PRIMARY KEY, ResponseID TEXT UNIQUE NOT NULL REFERENCES RESPONSE ON DELETE CASCADE,
 AudioFilePath TEXT NOT NULL, Duration REAL, FileFormat TEXT);
CREATE TABLE RESP_TRANS (
 TranscriptID TEXT PRIMARY KEY, ResponseID TEXT UNIQUE NOT NULL REFERENCES RESPONSE ON DELETE CASCADE,
 TranscriptText TEXT NOT NULL);
CREATE TABLE "SESSION" (
 SessionID TEXT PRIMARY KEY, StudentID INTEGER REFERENCES STUDENT ON DELETE SET NULL,
 ExamID TEXT REFERENCES EXAM ON DELETE SET NULL, CourseID TEXT REFERENCES COURSE ON DELETE SET NULL,
 StartTime TEXT NOT NULL, EndTime TEXT, SessionStatus TEXT NOT NULL DEFAULT 'active',
 QuestionIndex INTEGER NOT NULL DEFAULT 0, FollowUpCount INTEGER NOT NULL DEFAULT 0,
 CurrentPrompt TEXT NOT NULL DEFAULT '', UpdatedAt TEXT NOT NULL,
 LegacyCourseID TEXT, LegacyExamID TEXT, LegacyStudentID INTEGER,
 StudentUserName TEXT, StudentName TEXT);
CREATE TABLE STUDENT (
 StudentID INTEGER PRIMARY KEY REFERENCES "USER" ON DELETE CASCADE,
 UserID INTEGER UNIQUE NOT NULL REFERENCES "USER" ON DELETE CASCADE,
 JheID TEXT, FirstName TEXT, LastName TEXT, Email TEXT, CHECK(StudentID=UserID));
CREATE TABLE STUDENT_COURSE (
 StudentID INTEGER REFERENCES STUDENT ON DELETE CASCADE,
 CourseID TEXT REFERENCES COURSE ON DELETE CASCADE, PRIMARY KEY(StudentID,CourseID));
CREATE TABLE "USER" (
 UserID INTEGER PRIMARY KEY AUTOINCREMENT, UserName TEXT UNIQUE NOT NULL,
 PasswordHash TEXT NOT NULL, Role TEXT NOT NULL CHECK(Role IN ('faculty','student')),
 DisplayName TEXT NOT NULL, CreatedAt TEXT NOT NULL);
CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
INSERT INTO "schema_migrations" VALUES(1,'2026-10-29 18:24:50');
CREATE UNIQUE INDEX avatar_current ON AVATAR(ProfessorID) WHERE IsCurrent=1;
CREATE TRIGGER document_owner AFTER INSERT ON COURSE_DOC BEGIN
 UPDATE COURSE_DOC SET ProfessorID=(SELECT ProfessorID FROM COURSE WHERE CourseID=NEW.CourseID)
 WHERE DocumentID=NEW.DocumentID AND ProfessorID IS NULL;
END;
CREATE INDEX session_exam_start ON "SESSION"(ExamID,StartTime DESC);
CREATE INDEX interaction_question ON INTERACTION(QuestionID);
CREATE TRIGGER user_faculty AFTER INSERT ON "USER" WHEN NEW.Role='faculty'
 BEGIN INSERT INTO PROFESSOR(ProfessorID,UserID) VALUES(NEW.UserID,NEW.UserID); END;
CREATE TRIGGER user_student AFTER INSERT ON "USER" WHEN NEW.Role='student'
 BEGIN INSERT INTO STUDENT(StudentID,UserID) VALUES(NEW.UserID,NEW.UserID); END;
CREATE VIEW "users" AS SELECT "UserID" AS "id","UserName" AS "username","DisplayName" AS "display_name","Role" AS "role","PasswordHash" AS "pw_hash","CreatedAt" AS "created_at" FROM "USER";
CREATE TRIGGER "compat_users_INSERT" INSTEAD OF INSERT ON "users" BEGIN INSERT INTO "USER" ("UserID","UserName","DisplayName","Role","PasswordHash","CreatedAt") VALUES (NEW."id",NEW."username",NEW."display_name",NEW."role",NEW."pw_hash",NEW."created_at"); END;
CREATE TRIGGER "compat_users_UPDATE" INSTEAD OF UPDATE ON "users" BEGIN UPDATE "USER" SET "UserID"=NEW."id","UserName"=NEW."username","DisplayName"=NEW."display_name","Role"=NEW."role","PasswordHash"=NEW."pw_hash","CreatedAt"=NEW."created_at" WHERE "UserID"=OLD."id"; END;
CREATE TRIGGER "compat_users_DELETE" INSTEAD OF DELETE ON "users" BEGIN DELETE FROM "USER" WHERE "UserID"=OLD."id"; END;
CREATE VIEW "sessions" AS SELECT "TokenHash" AS "token_hash","UserID" AS "user_id","ExpiresAt" AS "expires_at" FROM "AUTH_SESSION";
CREATE TRIGGER "compat_sessions_INSERT" INSTEAD OF INSERT ON "sessions" BEGIN INSERT INTO "AUTH_SESSION" ("TokenHash","UserID","ExpiresAt") VALUES (NEW."token_hash",NEW."user_id",NEW."expires_at"); END;
CREATE TRIGGER "compat_sessions_UPDATE" INSTEAD OF UPDATE ON "sessions" BEGIN UPDATE "AUTH_SESSION" SET "TokenHash"=NEW."token_hash","UserID"=NEW."user_id","ExpiresAt"=NEW."expires_at" WHERE "TokenHash"=OLD."token_hash"; END;
CREATE TRIGGER "compat_sessions_DELETE" INSTEAD OF DELETE ON "sessions" BEGIN DELETE FROM "AUTH_SESSION" WHERE "TokenHash"=OLD."token_hash"; END;
CREATE VIEW "courses" AS SELECT "CourseID" AS "id","ProfessorID" AS "owner_id","CourseCode" AS "code","CourseName" AS "name","Term" AS "term","CreatedAt" AS "created_at" FROM "COURSE";
CREATE TRIGGER "compat_courses_INSERT" INSTEAD OF INSERT ON "courses" BEGIN INSERT INTO "COURSE" ("CourseID","ProfessorID","CourseCode","CourseName","Term","CreatedAt") VALUES (NEW."id",NEW."owner_id",NEW."code",NEW."name",NEW."term",NEW."created_at"); END;
CREATE TRIGGER "compat_courses_UPDATE" INSTEAD OF UPDATE ON "courses" BEGIN UPDATE "COURSE" SET "CourseID"=NEW."id","ProfessorID"=NEW."owner_id","CourseCode"=NEW."code","CourseName"=NEW."name","Term"=NEW."term","CreatedAt"=NEW."created_at" WHERE "CourseID"=OLD."id"; END;
CREATE TRIGGER "compat_courses_DELETE" INSTEAD OF DELETE ON "courses" BEGIN DELETE FROM "COURSE" WHERE "CourseID"=OLD."id"; END;
CREATE VIEW "materials" AS SELECT "DocumentID" AS "id","DocumentName" AS "filename","UploadedAt" AS "uploaded_at","Characters" AS "characters","CourseID" AS "course_id","FileSize" AS "size","RelativePath" AS "relative_path","FilePath" AS "storage_path" FROM "COURSE_DOC";
CREATE TRIGGER "compat_materials_INSERT" INSTEAD OF INSERT ON "materials" BEGIN INSERT INTO "COURSE_DOC" ("DocumentID","DocumentName","UploadedAt","Characters","CourseID","FileSize","RelativePath","FilePath") VALUES (NEW."id",NEW."filename",NEW."uploaded_at",NEW."characters",NEW."course_id",NEW."size",NEW."relative_path",NEW."storage_path"); END;
CREATE TRIGGER "compat_materials_UPDATE" INSTEAD OF UPDATE ON "materials" BEGIN UPDATE "COURSE_DOC" SET "DocumentID"=NEW."id","DocumentName"=NEW."filename","UploadedAt"=NEW."uploaded_at","Characters"=NEW."characters","CourseID"=NEW."course_id","FileSize"=NEW."size","RelativePath"=NEW."relative_path","FilePath"=NEW."storage_path" WHERE "DocumentID"=OLD."id"; END;
CREATE TRIGGER "compat_materials_DELETE" INSTEAD OF DELETE ON "materials" BEGIN DELETE FROM "COURSE_DOC" WHERE "DocumentID"=OLD."id"; END;
CREATE VIEW "chunks" AS SELECT "DocChunkID" AS "id","DocumentID" AS "material_id","Idx" AS "idx","Text" AS "text" FROM "DOC_CHUNKS";
CREATE TRIGGER "compat_chunks_INSERT" INSTEAD OF INSERT ON "chunks" BEGIN INSERT INTO "DOC_CHUNKS" ("DocChunkID","DocumentID","Idx","Text") VALUES (NEW."id",NEW."material_id",NEW."idx",NEW."text"); END;
CREATE TRIGGER "compat_chunks_UPDATE" INSTEAD OF UPDATE ON "chunks" BEGIN UPDATE "DOC_CHUNKS" SET "DocChunkID"=NEW."id","DocumentID"=NEW."material_id","Idx"=NEW."idx","Text"=NEW."text" WHERE "DocChunkID"=OLD."id"; END;
CREATE TRIGGER "compat_chunks_DELETE" INSTEAD OF DELETE ON "chunks" BEGIN DELETE FROM "DOC_CHUNKS" WHERE "DocChunkID"=OLD."id"; END;
CREATE VIEW exams AS SELECT ExamID id, LegacyCourse course, ExamTitle title,
 SettingsJSON settings,
 (SELECT json_group_array(json(QuestionData)) FROM
   (SELECT QuestionData FROM QUESTION_BANK WHERE ExamID=e.ExamID AND IsActive=1 ORDER BY SequenceNumber)) questions,
 ExamStatus status, CreatedAt created_at, PublishedAt published_at, CourseID course_id,
 ProfessorID professor_id, MediaVersion media_version FROM EXAM e WHERE DeletedAt IS NULL;
CREATE TRIGGER compat_exams_delete INSTEAD OF DELETE ON exams
 BEGIN UPDATE EXAM SET DeletedAt=CURRENT_TIMESTAMP WHERE ExamID=OLD.id; END;
CREATE TRIGGER compat_exams_INSERT INSTEAD OF INSERT ON exams BEGIN
          INSERT INTO EXAM(ExamID,CourseID,ExamTitle,ExamStatus,CreatedAt,PublishedAt,SettingsJSON,LegacyCourse,ProfessorID,MediaVersion,TimeLimit,PromptInstructions)
          VALUES(NEW.id,NEW.course_id,NEW.title,NEW.status,NEW.created_at,NEW.published_at,NEW.settings,NEW.course,NEW.professor_id,NEW.media_version,
            json_extract(NEW.settings,'$.seconds_per_question'),json_extract(NEW.settings,'$.prompt_instructions'))
          ON CONFLICT(ExamID) DO UPDATE SET CourseID=excluded.CourseID,ExamTitle=excluded.ExamTitle,
            ExamStatus=excluded.ExamStatus,CreatedAt=excluded.CreatedAt,PublishedAt=excluded.PublishedAt,
            SettingsJSON=excluded.SettingsJSON,LegacyCourse=excluded.LegacyCourse,ProfessorID=excluded.ProfessorID,
            MediaVersion=excluded.MediaVersion,TimeLimit=excluded.TimeLimit,PromptInstructions=excluded.PromptInstructions;
          UPDATE EXAM SET AvatarID=(SELECT AvatarID FROM AVATAR WHERE ProfessorID=NEW.professor_id AND MediaVersion=NEW.media_version) WHERE ExamID=NEW.id;
          UPDATE QUESTION_BANK SET IsActive=0 WHERE ExamID=NEW.id;
          INSERT INTO QUESTION_BANK(QuestionID,ExamID,ExternalQuestionID,QuestionText,QuestionSource,SequenceNumber,QuestionData,IsActive)
          SELECT NEW.id||':'||json_extract(value,'$.id'),NEW.id,json_extract(value,'$.id'),
            coalesce(json_extract(value,'$.question'),json_extract(value,'$.prompt'),''),
            CASE WHEN json_extract(value,'$.source_excerpt') LIKE 'Imported from%' THEN 'imported' ELSE 'generated' END,
            CAST(key AS INTEGER),value,1 FROM json_each(coalesce(NEW.questions,'[]')) WHERE 1
          ON CONFLICT(QuestionID) DO UPDATE SET QuestionText=excluded.QuestionText,QuestionSource=excluded.QuestionSource,
            SequenceNumber=excluded.SequenceNumber,QuestionData=excluded.QuestionData,IsActive=1;
          DELETE FROM EXAM_DOC WHERE ExamID=NEW.id;
          INSERT INTO EXAM_DOC SELECT NEW.id,value FROM json_each(NEW.settings,'$.material_ids')
            WHERE value IN (SELECT DocumentID FROM COURSE_DOC);
        END;
CREATE TRIGGER compat_exams_UPDATE INSTEAD OF UPDATE ON exams BEGIN
          INSERT INTO EXAM(ExamID,CourseID,ExamTitle,ExamStatus,CreatedAt,PublishedAt,SettingsJSON,LegacyCourse,ProfessorID,MediaVersion,TimeLimit,PromptInstructions)
          VALUES(NEW.id,NEW.course_id,NEW.title,NEW.status,NEW.created_at,NEW.published_at,NEW.settings,NEW.course,NEW.professor_id,NEW.media_version,
            json_extract(NEW.settings,'$.seconds_per_question'),json_extract(NEW.settings,'$.prompt_instructions'))
          ON CONFLICT(ExamID) DO UPDATE SET CourseID=excluded.CourseID,ExamTitle=excluded.ExamTitle,
            ExamStatus=excluded.ExamStatus,CreatedAt=excluded.CreatedAt,PublishedAt=excluded.PublishedAt,
            SettingsJSON=excluded.SettingsJSON,LegacyCourse=excluded.LegacyCourse,ProfessorID=excluded.ProfessorID,
            MediaVersion=excluded.MediaVersion,TimeLimit=excluded.TimeLimit,PromptInstructions=excluded.PromptInstructions;
          UPDATE EXAM SET AvatarID=(SELECT AvatarID FROM AVATAR WHERE ProfessorID=NEW.professor_id AND MediaVersion=NEW.media_version) WHERE ExamID=NEW.id;
          UPDATE QUESTION_BANK SET IsActive=0 WHERE ExamID=NEW.id;
          INSERT INTO QUESTION_BANK(QuestionID,ExamID,ExternalQuestionID,QuestionText,QuestionSource,SequenceNumber,QuestionData,IsActive)
          SELECT NEW.id||':'||json_extract(value,'$.id'),NEW.id,json_extract(value,'$.id'),
            coalesce(json_extract(value,'$.question'),json_extract(value,'$.prompt'),''),
            CASE WHEN json_extract(value,'$.source_excerpt') LIKE 'Imported from%' THEN 'imported' ELSE 'generated' END,
            CAST(key AS INTEGER),value,1 FROM json_each(coalesce(NEW.questions,'[]')) WHERE 1
          ON CONFLICT(QuestionID) DO UPDATE SET QuestionText=excluded.QuestionText,QuestionSource=excluded.QuestionSource,
            SequenceNumber=excluded.SequenceNumber,QuestionData=excluded.QuestionData,IsActive=1;
          DELETE FROM EXAM_DOC WHERE ExamID=NEW.id;
          INSERT INTO EXAM_DOC SELECT NEW.id,value FROM json_each(NEW.settings,'$.material_ids')
            WHERE value IN (SELECT DocumentID FROM COURSE_DOC);
        END;
CREATE VIEW assessment_sessions AS SELECT SessionID id,
 coalesce(CourseID,LegacyCourseID) course_id,coalesce(ExamID,LegacyExamID) exam_id,
 coalesce(StudentID,LegacyStudentID) student_id,StudentUserName student_username,StudentName student_name,
 QuestionIndex question_index,FollowUpCount follow_up_count,SessionStatus='completed' completed,
 CurrentPrompt current_prompt,StartTime created_at,UpdatedAt updated_at,EndTime completed_at FROM "SESSION";
CREATE TRIGGER compat_assessment_sessions_insert INSTEAD OF INSERT ON assessment_sessions BEGIN
 INSERT INTO "SESSION"(SessionID,StudentID,ExamID,CourseID,StartTime,EndTime,SessionStatus,QuestionIndex,FollowUpCount,CurrentPrompt,UpdatedAt,LegacyCourseID,LegacyExamID,LegacyStudentID,StudentUserName,StudentName)
 VALUES(NEW.id,(SELECT StudentID FROM STUDENT WHERE StudentID=NEW.student_id),
 (SELECT ExamID FROM EXAM WHERE ExamID=NEW.exam_id),(SELECT CourseID FROM COURSE WHERE CourseID=NEW.course_id),
 NEW.created_at,NEW.completed_at,CASE WHEN NEW.completed THEN 'completed' ELSE 'active' END,
 coalesce(NEW.question_index,0),coalesce(NEW.follow_up_count,0),coalesce(NEW.current_prompt,''),NEW.updated_at,
 NEW.course_id,NEW.exam_id,NEW.student_id,NEW.student_username,NEW.student_name);
 END;
CREATE TRIGGER compat_assessment_sessions_update INSTEAD OF UPDATE ON assessment_sessions BEGIN
 UPDATE "SESSION" SET QuestionIndex=NEW.question_index,FollowUpCount=NEW.follow_up_count,
 SessionStatus=CASE WHEN NEW.completed THEN 'completed' ELSE 'active' END,CurrentPrompt=NEW.current_prompt,
 UpdatedAt=NEW.updated_at,EndTime=NEW.completed_at WHERE SessionID=OLD.id;
 END;
CREATE VIEW assessment_turns AS SELECT i.InteractionID id,i.SessionID session_id,
 q.ExternalQuestionID question_id,i.SequenceNumber turn_number,i.ActualQuestion prompt,t.TranscriptText transcript,
 e.EvaluationJSON evaluation_json,i.RetrievedJSON retrieved_json,i.NextAction action,i.NextPrompt next_prompt,r.AnsweredAt created_at
 FROM INTERACTION i JOIN QUESTION_BANK q ON q.QuestionID=i.QuestionID
 JOIN RESPONSE r ON r.InteractionID=i.InteractionID JOIN RESP_TRANS t ON t.ResponseID=r.ResponseID
 JOIN EVALUATION e ON e.ResponseID=r.ResponseID;
CREATE TRIGGER compat_assessment_turns_insert INSTEAD OF INSERT ON assessment_turns BEGIN
 INSERT INTO QUESTION_BANK(QuestionID,ExamID,ExternalQuestionID,QuestionText,QuestionSource,SequenceNumber,QuestionData,IsActive)
 SELECT coalesce(s.ExamID,'legacy:'||NEW.session_id)||':'||NEW.question_id,s.ExamID,NEW.question_id,NEW.prompt,'legacy',NEW.turn_number,
 json_object('id',NEW.question_id,'question',NEW.prompt),0 FROM "SESSION" s WHERE s.SessionID=NEW.session_id
 ON CONFLICT(QuestionID) DO NOTHING;
 INSERT INTO INTERACTION VALUES(NEW.id,NEW.session_id,
 (SELECT coalesce(ExamID,'legacy:'||NEW.session_id)||':'||NEW.question_id FROM "SESSION" WHERE SessionID=NEW.session_id),
 NEW.prompt,NEW.turn_number,NEW.created_at,NEW.action,coalesce(NEW.next_prompt,''),NEW.retrieved_json);
 INSERT INTO RESPONSE VALUES(NEW.id,NEW.id,NEW.created_at);
 INSERT INTO RESP_TRANS VALUES(NEW.id,NEW.id,NEW.transcript);
 INSERT INTO EVALUATION VALUES(NEW.id,NEW.id,json_extract(NEW.evaluation_json,'$.rating'),json_extract(NEW.evaluation_json,'$.feedback'),NEW.evaluation_json);
 END;
CREATE VIEW professor_media AS SELECT ProfessorID user_id,MediaVersion version,UpdatedAt updated_at FROM AVATAR WHERE IsCurrent=1;
DELETE FROM "sqlite_sequence";
COMMIT;
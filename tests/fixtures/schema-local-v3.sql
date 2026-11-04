-- Earlier local v3 layout, schema only; no user data.
CREATE TABLE AUTH_SESSION (
 TokenHash TEXT PRIMARY KEY, UserID INTEGER NOT NULL REFERENCES "USER" ON DELETE CASCADE, ExpiresAt REAL NOT NULL);
CREATE TABLE CLIP_RESP (
 RespClip TEXT PRIMARY KEY, RecordingID TEXT REFERENCES RECORDING ON DELETE SET NULL,
 InteractionID TEXT NOT NULL REFERENCES INTERACTION ON DELETE CASCADE,
 AudioFilePath TEXT, StartTime REAL, EndTime REAL, FileFormat TEXT,
 Duration REAL, AnsweredAt TEXT NOT NULL, LegacyRecordingID TEXT UNIQUE,
 CHECK(StartTime IS NULL OR StartTime>=0),
 CHECK(EndTime IS NULL OR StartTime IS NULL OR EndTime>=StartTime));
CREATE TABLE CLIP_TRANS (
 TranscriptID TEXT PRIMARY KEY, RespClipID TEXT NOT NULL REFERENCES CLIP_RESP ON DELETE CASCADE,
 TranscriptText TEXT NOT NULL, Evaluation TEXT CHECK(Evaluation IS NULL OR json_valid(Evaluation)),
 EvaluationID TEXT UNIQUE, Rating REAL, Feedback TEXT);
CREATE TABLE COURSE (
 CourseID TEXT PRIMARY KEY, UserID INTEGER NOT NULL REFERENCES INSTRUCTOR(InstructorID),
 DepartmentID TEXT REFERENCES DEPARTMENT, CourseCode TEXT NOT NULL,
 CourseName TEXT NOT NULL, CourseDescription TEXT, Term TEXT, CreatedAt TEXT);
CREATE TABLE COURSE_DOC (
 DocumentID TEXT PRIMARY KEY, CourseID TEXT REFERENCES COURSE ON DELETE CASCADE,
 DocumentName TEXT, FilePath TEXT, FileType TEXT, UploadedAt TEXT,
 ProcessingStatus TEXT DEFAULT 'processed', Characters INTEGER, FileSize INTEGER, RelativePath TEXT);
CREATE TABLE DEPARTMENT (
 DepartmentID TEXT PRIMARY KEY, DepartmentName TEXT NOT NULL, DepartmentCode TEXT UNIQUE);
CREATE TABLE DOC_CHUNKS (
 DocChunkID INTEGER PRIMARY KEY AUTOINCREMENT, DocumentID TEXT REFERENCES COURSE_DOC ON DELETE CASCADE,
 Idx INTEGER, Text TEXT, UNIQUE(DocumentID,Idx));
CREATE TABLE EXAM (
 ExamID TEXT PRIMARY KEY, CourseID TEXT REFERENCES COURSE ON DELETE SET NULL,
 ExamTitle TEXT, ExamDescription TEXT, ExamStatus TEXT, TimeLimit INTEGER,
 CreatedAt TEXT, PublishedAt TEXT, PromptInstructions TEXT, SettingsJSON TEXT,
 LegacyCourse TEXT, UserID INTEGER REFERENCES INSTRUCTOR(InstructorID), MediaVersion TEXT, DeletedAt TEXT);
CREATE TABLE EXAM_DOC (
 ExamID TEXT NOT NULL REFERENCES EXAM ON DELETE CASCADE,
 DocumentID TEXT NOT NULL REFERENCES COURSE_DOC ON DELETE CASCADE, PRIMARY KEY(ExamID,DocumentID));
CREATE TABLE EXAM_PUBLICATION (
 ExamID TEXT PRIMARY KEY REFERENCES EXAM ON DELETE CASCADE,
 PublishedAt TEXT NOT NULL, PayloadJSON TEXT NOT NULL CHECK(json_valid(PayloadJSON)));
CREATE TABLE INSTRUCTOR (
 InstructorID INTEGER PRIMARY KEY REFERENCES "USER", DepartmentID TEXT REFERENCES DEPARTMENT,
 FaceImagePath TEXT, VoiceSamplePath TEXT, AvatarID TEXT UNIQUE, MediaVersion TEXT, UpdatedAt TEXT);
CREATE TABLE INTERACTION (
 InteractionID TEXT PRIMARY KEY, SessionID TEXT NOT NULL REFERENCES "SESSION" ON DELETE CASCADE,
 QuestionID TEXT NOT NULL REFERENCES QUEST_ESS, ActualQuestion TEXT NOT NULL,
 SequenceNumber INTEGER NOT NULL, AskedAt TEXT NOT NULL, NextAction TEXT NOT NULL,
 NextPrompt TEXT NOT NULL DEFAULT '', RetrievedJSON TEXT NOT NULL DEFAULT '[]',
 StartTime TEXT, EndTime TEXT, UNIQUE(SessionID,SequenceNumber));
CREATE TABLE QUEST_BANK (
 BankID TEXT PRIMARY KEY, ExamID TEXT REFERENCES EXAM ON DELETE CASCADE, DocSource TEXT);
CREATE TABLE QUEST_ESS (
 QuestionID TEXT PRIMARY KEY, BankID TEXT NOT NULL REFERENCES QUEST_BANK ON DELETE CASCADE,
 ExternalQuestionID TEXT NOT NULL, QuestionText TEXT NOT NULL, QuestionSource TEXT,
 SequenceNumber INTEGER NOT NULL, QuestionData TEXT NOT NULL,
 IsActive INTEGER NOT NULL DEFAULT 1 CHECK(IsActive IN (0,1)), UNIQUE(BankID,ExternalQuestionID));
CREATE TABLE RECORDING (
 RecordingID TEXT PRIMARY KEY, SessionID TEXT NOT NULL REFERENCES "SESSION" ON DELETE CASCADE,
 StartTime TEXT, EndTime TEXT, RecordingPath TEXT NOT NULL);
CREATE TABLE SECTION (
 SectionID TEXT PRIMARY KEY, InstructorID INTEGER NOT NULL REFERENCES INSTRUCTOR,
 CourseID TEXT NOT NULL REFERENCES COURSE ON DELETE CASCADE, SectionNumber TEXT NOT NULL,
 UNIQUE(CourseID,SectionNumber));
CREATE TABLE "SESSION" (
 SessionID TEXT PRIMARY KEY, StudentID INTEGER REFERENCES STUDENT ON DELETE SET NULL,
 InstructorID INTEGER REFERENCES INSTRUCTOR ON DELETE SET NULL,
 ExamID TEXT REFERENCES EXAM ON DELETE SET NULL, CourseID TEXT REFERENCES COURSE ON DELETE SET NULL,
 StartTime TEXT NOT NULL, EndTime TEXT, SessionStatus TEXT NOT NULL DEFAULT 'active',
 QuestionIndex INTEGER NOT NULL DEFAULT 0, FollowUpCount INTEGER NOT NULL DEFAULT 0,
 CurrentPrompt TEXT NOT NULL DEFAULT '', UpdatedAt TEXT NOT NULL,
 LegacyCourseID TEXT, LegacyExamID TEXT, LegacyStudentID INTEGER,
 StudentUserName TEXT, StudentName TEXT);
CREATE TABLE STUDENT (StudentID INTEGER PRIMARY KEY REFERENCES "USER");
CREATE TABLE STUDENT_SEC (
 StudentID INTEGER NOT NULL REFERENCES STUDENT, SectionID TEXT NOT NULL REFERENCES SECTION ON DELETE CASCADE,
 PRIMARY KEY(StudentID,SectionID));
CREATE TABLE "USER" (
 UserID INTEGER PRIMARY KEY AUTOINCREMENT, UserName TEXT UNIQUE NOT NULL,
 PasswordHash TEXT NOT NULL, Role TEXT NOT NULL CHECK(Role IN ('faculty','student')),
 DisplayName TEXT NOT NULL, CreatedAt TEXT NOT NULL, Email TEXT, FirstName TEXT, LastName TEXT);
CREATE TABLE analytics_model_calls (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    operation TEXT NOT NULL,
                    model TEXT NOT NULL,
                    input_tokens INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL,
                    duration_ms REAL,
                    load_duration_ms REAL,
                    prompt_eval_duration_ms REAL,
                    eval_duration_ms REAL,
                    item_count INTEGER,
                    FOREIGN KEY(run_id) REFERENCES analytics_runs(id)
                );
CREATE TABLE analytics_runs (
                    id TEXT PRIMARY KEY,
                    run_type TEXT NOT NULL,
                    session_id TEXT,
                    question_id TEXT,
                    started_at TEXT NOT NULL,
                    duration_ms REAL NOT NULL,
                    cpu_time_ms REAL NOT NULL,
                    process_max_rss_mb REAL NOT NULL,
                    input_tokens INTEGER NOT NULL,
                    output_tokens INTEGER NOT NULL,
                    base_energy_wh_est REAL NOT NULL,
                    gpu_energy_wh_est REAL NOT NULL,
                    total_energy_wh_est REAL NOT NULL,
                    gpu_average_watts REAL NOT NULL,
                    gpu_samples INTEGER NOT NULL,
                    energy_method TEXT NOT NULL,
                    success INTEGER NOT NULL,
                    error_type TEXT,
                    stages_json TEXT NOT NULL,
                    metrics_json TEXT NOT NULL
                );
CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
CREATE INDEX analytics_model_calls_run_id
                    ON analytics_model_calls(run_id);
CREATE INDEX analytics_runs_started_at
                    ON analytics_runs(started_at DESC);
CREATE INDEX clip_interaction ON CLIP_RESP(InteractionID);
CREATE INDEX clip_recording ON CLIP_RESP(RecordingID);
CREATE INDEX clip_trans_response ON CLIP_TRANS(RespClipID);
CREATE INDEX interaction_question ON INTERACTION(QuestionID);
CREATE INDEX quest_bank_exam ON QUEST_BANK(ExamID);
CREATE INDEX session_exam_start ON "SESSION"(ExamID,StartTime DESC);
CREATE VIEW AVATAR AS SELECT AvatarID,InstructorID UserID,FaceImagePath,VoiceSamplePath,MediaVersion,UpdatedAt
 FROM INSTRUCTOR WHERE MediaVersion IS NOT NULL;
CREATE VIEW EVALUATION AS SELECT EvaluationID,RespClipID ResponseID,Rating,Feedback,Evaluation EvaluationJSON
 FROM CLIP_TRANS WHERE Evaluation IS NOT NULL;
CREATE VIEW QUESTION_BANK AS SELECT q.QuestionID,b.ExamID,q.ExternalQuestionID,q.QuestionText,
 q.QuestionSource,q.SequenceNumber,q.QuestionData,q.IsActive
 FROM QUEST_ESS q JOIN QUEST_BANK b ON b.BankID=q.BankID;
CREATE VIEW RESPONSE AS SELECT RespClip ResponseID,InteractionID,AnsweredAt FROM CLIP_RESP;
CREATE VIEW RESP_REC AS SELECT coalesce(LegacyRecordingID,RespClip) RecordingID,RespClip ResponseID,AudioFilePath,Duration,FileFormat
 FROM CLIP_RESP WHERE AudioFilePath IS NOT NULL;
CREATE VIEW RESP_TRANS AS SELECT TranscriptID,RespClipID ResponseID,TranscriptText FROM CLIP_TRANS;
CREATE VIEW USER_COURSE AS SELECT DISTINCT s.StudentID UserID,sec.CourseID
 FROM STUDENT_SEC s JOIN SECTION sec ON sec.SectionID=s.SectionID;
CREATE VIEW USER_DEPART AS SELECT InstructorID UserID,DepartmentID FROM INSTRUCTOR WHERE DepartmentID IS NOT NULL;
CREATE VIEW assessment_sessions AS SELECT SessionID id,
 coalesce(CourseID,LegacyCourseID) course_id,coalesce(ExamID,LegacyExamID) exam_id,
 coalesce(StudentID,LegacyStudentID) student_id,StudentUserName student_username,StudentName student_name,
 QuestionIndex question_index,FollowUpCount follow_up_count,SessionStatus='completed' completed,
 CurrentPrompt current_prompt,StartTime created_at,UpdatedAt updated_at,EndTime completed_at FROM "SESSION";
CREATE VIEW assessment_turns AS SELECT i.InteractionID id,i.SessionID session_id,
 q.ExternalQuestionID question_id,i.SequenceNumber turn_number,i.ActualQuestion prompt,t.TranscriptText transcript,
 t.Evaluation evaluation_json,i.RetrievedJSON retrieved_json,i.NextAction action,i.NextPrompt next_prompt,r.AnsweredAt created_at
 FROM INTERACTION i JOIN QUEST_ESS q ON q.QuestionID=i.QuestionID
 JOIN CLIP_RESP r ON r.InteractionID=i.InteractionID
 JOIN CLIP_TRANS t ON t.RespClipID=r.RespClip
 WHERE r.RespClip=(SELECT c.RespClip FROM CLIP_RESP c WHERE c.InteractionID=i.InteractionID
   AND EXISTS(SELECT 1 FROM CLIP_TRANS ct WHERE ct.RespClipID=c.RespClip AND ct.Evaluation IS NOT NULL)
   ORDER BY c.AnsweredAt DESC,c.RespClip DESC LIMIT 1)
 AND t.rowid=(SELECT ct.rowid FROM CLIP_TRANS ct WHERE ct.RespClipID=r.RespClip AND ct.Evaluation IS NOT NULL
   ORDER BY ct.rowid DESC LIMIT 1);
CREATE VIEW "chunks" AS SELECT "DocChunkID" AS "id","DocumentID" AS "material_id","Idx" AS "idx","Text" AS "text" FROM "DOC_CHUNKS";
CREATE VIEW "courses" AS SELECT "CourseID" AS "id","UserID" AS "owner_id","CourseCode" AS "code","CourseName" AS "name","Term" AS "term","CreatedAt" AS "created_at" FROM "COURSE";
CREATE VIEW exams AS SELECT ExamID id, LegacyCourse course, ExamTitle title,
 SettingsJSON settings,
 (SELECT json_group_array(json(QuestionData)) FROM
   (SELECT QuestionData FROM QUESTION_BANK WHERE ExamID=e.ExamID AND IsActive=1 ORDER BY SequenceNumber)) questions,
 ExamStatus status, CreatedAt created_at, PublishedAt published_at, CourseID course_id,
 UserID professor_id, MediaVersion media_version FROM EXAM e WHERE DeletedAt IS NULL;
CREATE VIEW "materials" AS SELECT "DocumentID" AS "id","DocumentName" AS "filename","UploadedAt" AS "uploaded_at","Characters" AS "characters","CourseID" AS "course_id","FileSize" AS "size","RelativePath" AS "relative_path","FilePath" AS "storage_path" FROM "COURSE_DOC";
CREATE VIEW professor_media AS SELECT UserID user_id,MediaVersion version,UpdatedAt updated_at FROM AVATAR;
CREATE VIEW "sessions" AS SELECT "TokenHash" AS "token_hash","UserID" AS "user_id","ExpiresAt" AS "expires_at" FROM "AUTH_SESSION";
CREATE VIEW "users" AS SELECT "UserID" AS "id","UserName" AS "username","DisplayName" AS "display_name","Role" AS "role","PasswordHash" AS "pw_hash","CreatedAt" AS "created_at" FROM "USER";
CREATE TRIGGER clip_session_insert BEFORE INSERT ON CLIP_RESP WHEN NEW.RecordingID IS NOT NULL BEGIN
 SELECT RAISE(ABORT,'Recording and interaction belong to different sessions')
 WHERE (SELECT SessionID FROM RECORDING WHERE RecordingID=NEW.RecordingID)
    IS NOT (SELECT SessionID FROM INTERACTION WHERE InteractionID=NEW.InteractionID);
END;
CREATE TRIGGER clip_session_update BEFORE UPDATE OF RecordingID,InteractionID ON CLIP_RESP WHEN NEW.RecordingID IS NOT NULL BEGIN
 SELECT RAISE(ABORT,'Recording and interaction belong to different sessions')
 WHERE (SELECT SessionID FROM RECORDING WHERE RecordingID=NEW.RecordingID)
    IS NOT (SELECT SessionID FROM INTERACTION WHERE InteractionID=NEW.InteractionID);
END;
CREATE TRIGGER compat_assessment_sessions_insert INSTEAD OF INSERT ON assessment_sessions BEGIN
 INSERT INTO "SESSION"(SessionID,StudentID,InstructorID,ExamID,CourseID,StartTime,EndTime,SessionStatus,QuestionIndex,FollowUpCount,CurrentPrompt,UpdatedAt,LegacyCourseID,LegacyExamID,LegacyStudentID,StudentUserName,StudentName)
 VALUES(NEW.id,(SELECT StudentID FROM STUDENT WHERE StudentID=NEW.student_id),
 (SELECT UserID FROM COURSE WHERE CourseID=NEW.course_id),
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
CREATE TRIGGER compat_assessment_turns_insert INSTEAD OF INSERT ON assessment_turns BEGIN
 INSERT INTO QUEST_BANK(BankID,ExamID)
 SELECT 'bank:'||coalesce(ExamID,'legacy:'||NEW.session_id),ExamID FROM "SESSION" WHERE SessionID=NEW.session_id
 ON CONFLICT(BankID) DO NOTHING;
 INSERT INTO QUEST_ESS(QuestionID,BankID,ExternalQuestionID,QuestionText,QuestionSource,SequenceNumber,QuestionData,IsActive)
 SELECT coalesce(s.ExamID,'legacy:'||NEW.session_id)||':'||NEW.question_id,'bank:'||coalesce(s.ExamID,'legacy:'||NEW.session_id),NEW.question_id,NEW.prompt,'legacy',NEW.turn_number,
 json_object('id',NEW.question_id,'question',NEW.prompt),0 FROM "SESSION" s WHERE s.SessionID=NEW.session_id
 ON CONFLICT(QuestionID) DO NOTHING;
 INSERT INTO INTERACTION(InteractionID,SessionID,QuestionID,ActualQuestion,SequenceNumber,AskedAt,NextAction,NextPrompt,RetrievedJSON) VALUES(NEW.id,NEW.session_id,
 (SELECT coalesce(ExamID,'legacy:'||NEW.session_id)||':'||NEW.question_id FROM "SESSION" WHERE SessionID=NEW.session_id),
 NEW.prompt,NEW.turn_number,NEW.created_at,NEW.action,coalesce(NEW.next_prompt,''),NEW.retrieved_json);
 INSERT INTO CLIP_RESP(RespClip,InteractionID,AnsweredAt) VALUES(NEW.id,NEW.id,NEW.created_at);
 INSERT INTO CLIP_TRANS(TranscriptID,RespClipID,TranscriptText,EvaluationID,Rating,Feedback,Evaluation)
 VALUES(NEW.id,NEW.id,NEW.transcript,NEW.id,json_extract(NEW.evaluation_json,'$.rating'),json_extract(NEW.evaluation_json,'$.feedback'),NEW.evaluation_json);
 END;
CREATE TRIGGER "compat_chunks_DELETE" INSTEAD OF DELETE ON "chunks" BEGIN DELETE FROM "DOC_CHUNKS" WHERE "DocChunkID"=OLD."id"; END;
CREATE TRIGGER "compat_chunks_INSERT" INSTEAD OF INSERT ON "chunks" BEGIN INSERT INTO "DOC_CHUNKS" ("DocChunkID","DocumentID","Idx","Text") VALUES (NEW."id",NEW."material_id",NEW."idx",NEW."text"); END;
CREATE TRIGGER "compat_chunks_UPDATE" INSTEAD OF UPDATE ON "chunks" BEGIN UPDATE "DOC_CHUNKS" SET "DocChunkID"=NEW."id","DocumentID"=NEW."material_id","Idx"=NEW."idx","Text"=NEW."text" WHERE "DocChunkID"=OLD."id"; END;
CREATE TRIGGER "compat_courses_DELETE" INSTEAD OF DELETE ON "courses" BEGIN DELETE FROM "COURSE" WHERE "CourseID"=OLD."id"; END;
CREATE TRIGGER "compat_courses_INSERT" INSTEAD OF INSERT ON "courses" BEGIN INSERT INTO "COURSE" ("CourseID","UserID","CourseCode","CourseName","Term","CreatedAt") VALUES (NEW."id",NEW."owner_id",NEW."code",NEW."name",NEW."term",NEW."created_at"); END;
CREATE TRIGGER "compat_courses_UPDATE" INSTEAD OF UPDATE ON "courses" BEGIN UPDATE "COURSE" SET "CourseID"=NEW."id","UserID"=NEW."owner_id","CourseCode"=NEW."code","CourseName"=NEW."name","Term"=NEW."term","CreatedAt"=NEW."created_at" WHERE "CourseID"=OLD."id"; END;
CREATE TRIGGER compat_enrollment_delete INSTEAD OF DELETE ON USER_COURSE BEGIN
 DELETE FROM STUDENT_SEC WHERE StudentID=OLD.UserID AND SectionID IN (SELECT SectionID FROM SECTION WHERE CourseID=OLD.CourseID);
END;
CREATE TRIGGER compat_enrollment_insert INSTEAD OF INSERT ON USER_COURSE BEGIN
 INSERT INTO SECTION(SectionID,InstructorID,CourseID,SectionNumber)
 SELECT 'legacy-section:'||CourseID,UserID,CourseID,'legacy' FROM COURSE WHERE CourseID=NEW.CourseID
 ON CONFLICT(CourseID,SectionNumber) DO NOTHING;
 INSERT INTO STUDENT_SEC(StudentID,SectionID)
 SELECT NEW.UserID,SectionID FROM SECTION WHERE CourseID=NEW.CourseID AND SectionNumber='legacy';
 SELECT RAISE(ABORT,'Unknown course') WHERE NOT EXISTS(SELECT 1 FROM COURSE WHERE CourseID=NEW.CourseID);
END;
CREATE TRIGGER compat_exams_INSERT INSTEAD OF INSERT ON exams BEGIN
          INSERT INTO EXAM(ExamID,CourseID,ExamTitle,ExamStatus,CreatedAt,PublishedAt,SettingsJSON,LegacyCourse,UserID,MediaVersion,TimeLimit,PromptInstructions)
          VALUES(NEW.id,NEW.course_id,NEW.title,NEW.status,NEW.created_at,NEW.published_at,NEW.settings,NEW.course,NEW.professor_id,NEW.media_version,
            json_extract(NEW.settings,'$.seconds_per_question'),json_extract(NEW.settings,'$.prompt_instructions'))
          ON CONFLICT(ExamID) DO UPDATE SET CourseID=excluded.CourseID,ExamTitle=excluded.ExamTitle,
            ExamStatus=excluded.ExamStatus,CreatedAt=excluded.CreatedAt,PublishedAt=excluded.PublishedAt,
            SettingsJSON=excluded.SettingsJSON,LegacyCourse=excluded.LegacyCourse,UserID=excluded.UserID,
            MediaVersion=excluded.MediaVersion,TimeLimit=excluded.TimeLimit,PromptInstructions=excluded.PromptInstructions;
          UPDATE QUEST_ESS SET IsActive=0 WHERE BankID IN (SELECT BankID FROM QUEST_BANK WHERE ExamID=NEW.id);
          INSERT INTO QUEST_ESS(QuestionID,BankID,ExternalQuestionID,QuestionText,QuestionSource,SequenceNumber,QuestionData,IsActive)
          SELECT NEW.id||':'||json_extract(value,'$.id'),'bank:'||NEW.id,json_extract(value,'$.id'),
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
          INSERT INTO EXAM(ExamID,CourseID,ExamTitle,ExamStatus,CreatedAt,PublishedAt,SettingsJSON,LegacyCourse,UserID,MediaVersion,TimeLimit,PromptInstructions)
          VALUES(NEW.id,NEW.course_id,NEW.title,NEW.status,NEW.created_at,NEW.published_at,NEW.settings,NEW.course,NEW.professor_id,NEW.media_version,
            json_extract(NEW.settings,'$.seconds_per_question'),json_extract(NEW.settings,'$.prompt_instructions'))
          ON CONFLICT(ExamID) DO UPDATE SET CourseID=excluded.CourseID,ExamTitle=excluded.ExamTitle,
            ExamStatus=excluded.ExamStatus,CreatedAt=excluded.CreatedAt,PublishedAt=excluded.PublishedAt,
            SettingsJSON=excluded.SettingsJSON,LegacyCourse=excluded.LegacyCourse,UserID=excluded.UserID,
            MediaVersion=excluded.MediaVersion,TimeLimit=excluded.TimeLimit,PromptInstructions=excluded.PromptInstructions;
          UPDATE QUEST_ESS SET IsActive=0 WHERE BankID IN (SELECT BankID FROM QUEST_BANK WHERE ExamID=NEW.id);
          INSERT INTO QUEST_ESS(QuestionID,BankID,ExternalQuestionID,QuestionText,QuestionSource,SequenceNumber,QuestionData,IsActive)
          SELECT NEW.id||':'||json_extract(value,'$.id'),'bank:'||NEW.id,json_extract(value,'$.id'),
            coalesce(json_extract(value,'$.question'),json_extract(value,'$.prompt'),''),
            CASE WHEN json_extract(value,'$.source_excerpt') LIKE 'Imported from%' THEN 'imported' ELSE 'generated' END,
            CAST(key AS INTEGER),value,1 FROM json_each(coalesce(NEW.questions,'[]')) WHERE 1
          ON CONFLICT(QuestionID) DO UPDATE SET QuestionText=excluded.QuestionText,QuestionSource=excluded.QuestionSource,
            SequenceNumber=excluded.SequenceNumber,QuestionData=excluded.QuestionData,IsActive=1;
          DELETE FROM EXAM_DOC WHERE ExamID=NEW.id;
          INSERT INTO EXAM_DOC SELECT NEW.id,value FROM json_each(NEW.settings,'$.material_ids')
            WHERE value IN (SELECT DocumentID FROM COURSE_DOC);
        END;
CREATE TRIGGER compat_exams_delete INSTEAD OF DELETE ON exams
 BEGIN UPDATE EXAM SET DeletedAt=CURRENT_TIMESTAMP WHERE ExamID=OLD.id; END;
CREATE TRIGGER "compat_materials_DELETE" INSTEAD OF DELETE ON "materials" BEGIN DELETE FROM "COURSE_DOC" WHERE "DocumentID"=OLD."id"; END;
CREATE TRIGGER "compat_materials_INSERT" INSTEAD OF INSERT ON "materials" BEGIN INSERT INTO "COURSE_DOC" ("DocumentID","DocumentName","UploadedAt","Characters","CourseID","FileSize","RelativePath","FilePath") VALUES (NEW."id",NEW."filename",NEW."uploaded_at",NEW."characters",NEW."course_id",NEW."size",NEW."relative_path",NEW."storage_path"); END;
CREATE TRIGGER "compat_materials_UPDATE" INSTEAD OF UPDATE ON "materials" BEGIN UPDATE "COURSE_DOC" SET "DocumentID"=NEW."id","DocumentName"=NEW."filename","UploadedAt"=NEW."uploaded_at","Characters"=NEW."characters","CourseID"=NEW."course_id","FileSize"=NEW."size","RelativePath"=NEW."relative_path","FilePath"=NEW."storage_path" WHERE "DocumentID"=OLD."id"; END;
CREATE TRIGGER "compat_sessions_DELETE" INSTEAD OF DELETE ON "sessions" BEGIN DELETE FROM "AUTH_SESSION" WHERE "TokenHash"=OLD."token_hash"; END;
CREATE TRIGGER "compat_sessions_INSERT" INSTEAD OF INSERT ON "sessions" BEGIN INSERT INTO "AUTH_SESSION" ("TokenHash","UserID","ExpiresAt") VALUES (NEW."token_hash",NEW."user_id",NEW."expires_at"); END;
CREATE TRIGGER "compat_sessions_UPDATE" INSTEAD OF UPDATE ON "sessions" BEGIN UPDATE "AUTH_SESSION" SET "TokenHash"=NEW."token_hash","UserID"=NEW."user_id","ExpiresAt"=NEW."expires_at" WHERE "TokenHash"=OLD."token_hash"; END;
CREATE TRIGGER "compat_users_DELETE" INSTEAD OF DELETE ON "users" BEGIN DELETE FROM "USER" WHERE "UserID"=OLD."id"; END;
CREATE TRIGGER "compat_users_INSERT" INSTEAD OF INSERT ON "users" BEGIN INSERT INTO "USER" ("UserID","UserName","DisplayName","Role","PasswordHash","CreatedAt") VALUES (NEW."id",NEW."username",NEW."display_name",NEW."role",NEW."pw_hash",NEW."created_at"); END;
CREATE TRIGGER "compat_users_UPDATE" INSTEAD OF UPDATE ON "users" BEGIN UPDATE "USER" SET "UserID"=NEW."id","UserName"=NEW."username","DisplayName"=NEW."display_name","Role"=NEW."role","PasswordHash"=NEW."pw_hash","CreatedAt"=NEW."created_at" WHERE "UserID"=OLD."id"; END;
CREATE TRIGGER exam_bank_insert AFTER INSERT ON EXAM BEGIN
 INSERT INTO QUEST_BANK(BankID,ExamID) VALUES('bank:'||NEW.ExamID,NEW.ExamID);
END;
CREATE TRIGGER interaction_session_update BEFORE UPDATE OF SessionID ON INTERACTION BEGIN
 SELECT RAISE(ABORT,'Recording and interaction belong to different sessions')
 WHERE EXISTS(SELECT 1 FROM CLIP_RESP c JOIN RECORDING r ON r.RecordingID=c.RecordingID
              WHERE c.InteractionID=OLD.InteractionID AND r.SessionID IS NOT NEW.SessionID);
END;
CREATE TRIGGER recording_session_update BEFORE UPDATE OF SessionID ON RECORDING BEGIN
 SELECT RAISE(ABORT,'Recording and interaction belong to different sessions')
 WHERE EXISTS(SELECT 1 FROM CLIP_RESP c JOIN INTERACTION i ON i.InteractionID=c.InteractionID
              WHERE c.RecordingID=OLD.RecordingID AND i.SessionID IS NOT NEW.SessionID);
END;
CREATE TRIGGER user_profile_insert AFTER INSERT ON "USER" BEGIN
 INSERT INTO INSTRUCTOR(InstructorID) SELECT NEW.UserID WHERE NEW.Role='faculty';
 INSERT INTO STUDENT(StudentID) SELECT NEW.UserID WHERE NEW.Role='student';
END;
CREATE TRIGGER user_profile_update AFTER UPDATE OF Role ON "USER" BEGIN
 INSERT OR IGNORE INTO INSTRUCTOR(InstructorID) SELECT NEW.UserID WHERE NEW.Role='faculty';
 INSERT OR IGNORE INTO STUDENT(StudentID) SELECT NEW.UserID WHERE NEW.Role='student';
END;
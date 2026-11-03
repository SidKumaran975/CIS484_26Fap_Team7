-- Read adapters for existing reports and API queries; no duplicate data stores.
CREATE VIEW IF NOT EXISTS QUESTION_BANK AS SELECT q.QuestionID,b.ExamID,q.ExternalQuestionID,q.QuestionText,
 q.QuestionSource,q.SequenceNumber,q.QuestionData,q.IsActive
 FROM QUEST_ESS q JOIN QUEST_BANK b ON b.BankID=q.BankID;
CREATE VIEW IF NOT EXISTS AVATAR AS SELECT AvatarID,InstructorID UserID,FaceImagePath,VoiceSamplePath,MediaVersion,UpdatedAt
 FROM INSTRUCTOR WHERE MediaVersion IS NOT NULL;
CREATE VIEW IF NOT EXISTS USER_DEPART AS SELECT InstructorID UserID,DepartmentID FROM INSTRUCTOR WHERE DepartmentID IS NOT NULL;
CREATE VIEW IF NOT EXISTS USER_COURSE AS SELECT DISTINCT s.StudentID UserID,sec.CourseID
 FROM STUDENT_SEC s JOIN SECTION sec ON sec.SectionID=s.SectionID;
CREATE TRIGGER IF NOT EXISTS compat_enrollment_insert INSTEAD OF INSERT ON USER_COURSE BEGIN
 INSERT INTO SECTION(SectionID,InstructorID,CourseID,SectionNumber)
 SELECT 'legacy-section:'||CourseID,UserID,CourseID,'legacy' FROM COURSE WHERE CourseID=NEW.CourseID
 ON CONFLICT(CourseID,SectionNumber) DO NOTHING;
 INSERT INTO STUDENT_SEC(StudentID,SectionID)
 SELECT NEW.UserID,SectionID FROM SECTION WHERE CourseID=NEW.CourseID AND SectionNumber='legacy';
 SELECT RAISE(ABORT,'Unknown course') WHERE NOT EXISTS(SELECT 1 FROM COURSE WHERE CourseID=NEW.CourseID);
END;
CREATE TRIGGER IF NOT EXISTS compat_enrollment_delete INSTEAD OF DELETE ON USER_COURSE BEGIN
 DELETE FROM STUDENT_SEC WHERE StudentID=OLD.UserID AND SectionID IN (SELECT SectionID FROM SECTION WHERE CourseID=OLD.CourseID);
END;
CREATE VIEW IF NOT EXISTS RESPONSE AS SELECT RespClip ResponseID,InteractionID,AnsweredAt FROM CLIP_RESP;
CREATE VIEW IF NOT EXISTS RESP_TRANS AS SELECT TranscriptID,RespClipID ResponseID,TranscriptText FROM CLIP_TRANS;
CREATE VIEW IF NOT EXISTS EVALUATION AS SELECT EvaluationID,RespClipID ResponseID,Rating,Feedback,Evaluation EvaluationJSON
 FROM CLIP_TRANS WHERE Evaluation IS NOT NULL;
CREATE VIEW IF NOT EXISTS RESP_REC AS SELECT coalesce(LegacyRecordingID,RespClip) RecordingID,RespClip ResponseID,AudioFilePath,Duration,FileFormat
 FROM CLIP_RESP WHERE AudioFilePath IS NOT NULL;

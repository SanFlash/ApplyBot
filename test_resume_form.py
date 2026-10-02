from resume_form import answer_for_descriptor, build_resume_answers, option_match


def test_resume_mapping_matches_common_form_labels():
    answers = build_resume_answers(
        {
            "name": "Satyendra Kumar Namdeo",
            "email": "test@example.com",
            "phone": "9999999999",
            "experience_years": 1,
            "notice_period_days": 45,
            "current_ctc_lpa": 2.2,
            "skills": ["Playwright", "Python", "Appium"],
        },
        {"title": "QA Automation Engineer", "company": "Example"},
        {"why_interested": "QA role", "expected_salary": "₹4–5 LPA"},
    )
    assert answer_for_descriptor("First Name", answers) == ("first_name", "Satyendra")
    assert answer_for_descriptor("Email Address", answers) == ("email", "test@example.com")
    assert answer_for_descriptor("Mobile Number", answers) == ("phone", "9999999999")
    assert answer_for_descriptor("Years of experience", answers) == ("experience_years", "1")
    assert answer_for_descriptor("Notice period", answers) == ("notice_period_days", "45")
    assert answer_for_descriptor("Expected CTC", answers) == ("expected_ctc", "₹4–5 LPA")
    assert answer_for_descriptor("LinkedIn profile URL", answers)[0] == "linkedin"
    assert "Playwright" in answer_for_descriptor("Technical skills", answers)[1]


def test_resume_mapping_leaves_unknown_questions_unanswered():
    answers = build_resume_answers(
        {"name": "Satyendra Kumar Namdeo", "skills": ["Playwright"]},
        {"title": "QA Engineer", "company": "Example"},
        {},
    )
    assert answer_for_descriptor("What is your favorite programming language?", answers) == (None, None)
    assert answer_for_descriptor("Date of birth", answers) == (None, None)


def test_option_matching_is_conservative():
    assert option_match(["Yes", "No"], "Yes") == "Yes"
    assert option_match(["Yes", "No"], "No") == "No"
    assert option_match(["Remote", "Hybrid", "On-site"], "remote") == "Remote"
    assert option_match(["Bengaluru", "Pune", "Bhopal"], "Pune") == "Pune"
    assert option_match(["Yes", "No"], "Something unrelated") is None

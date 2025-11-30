from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash

from .models import User
from . import db, send_email_safe


auth = Blueprint('auth', __name__)

# this code is for logging and signing in only, with its error handling

# Login Page logic
@auth.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')

        try:
            user = User.query.filter_by(email=email).first()
        except Exception:
            db.session.rollback()
            user = User.query.filter_by(email=email).first()

        try:
            if user:
                if check_password_hash(user.password, password):
                    flash('Login successfull!', category='success')
                    login_user(user, remember=True)
                    return redirect(url_for('views.home'))
                else:
                    flash('The password is incorrect, please try again.', category='error')
            else:
                flash('No user is registered under this email.', category='error')

        except Exception as e:
            # Debug output in console
            print("Login error:", e)
            flash('There was an error processing the data. Please try again..', category='error')

    return render_template("login.html", user=current_user)


# Logout function
@auth.route('/logout')
@login_required
def logout():
    try:
        logout_user()
    except Exception as e:
        print("Logout error:", e)
        flash('There was an error logging out. Please try again.', category='error')

    return redirect(url_for('auth.login'))


# Sign up Page
@auth.route('/sign-up', methods=['GET', 'POST'])
def sign_up():
    if request.method == 'POST':
        email = request.form.get('email')
        email1 = request.form.get('email1')
        user_name = request.form.get('user_name')
        password1 = request.form.get('password1')
        password2 = request.form.get('password2')

        try:
            user = User.query.filter_by(email=email).first()
        except Exception:
            db.session.rollback()
            user = User.query.filter_by(email=email).first()

        try:
            if user:
                flash('The email is already assigned to a user', category='error')
            elif len(email) < 4:
                flash('The email must be longer than 4 letters.', category='error')
            elif email != email1:
                flash('The emails do not match.', category='error')
            elif len(user_name) < 2:
                flash('The username must be longer than two letters.', category='error')
            elif password1 != password2:
                flash('The passwords do not match.', category='error')
            elif len(password1) < 7:
                flash('The password must be at least 8 characters long.', category='error')
            else:
                # Nutzer anlegen – Standard-Hash verwenden (pbkdf2:sha256)
                new_user = User(
                    email=email,
                    user_name=user_name,
                    password=generate_password_hash(password1)  # default = pbkdf2:sha256
                )
                db.session.add(new_user)
                db.session.commit()

                # 📧 E-MAIL AN DEN NEUEN NUTZER SENDEN
                                # 📧 E-MAIL AN DEN NEUEN NUTZER SENDEN
                                # 📧 E-MAIL AN DEN NEUEN NUTZER SENDEN
                ok = send_email_safe(
                    subject="Tolerance Together – Registration Confirmation",
                    recipients=[email],
                    body=(
                        f"Hello,\n\n"
                        f"Your account on Tolerance Together has been successfully created with the email: {email}.\n\n"
                        f"If this was NOT you, please contact us immediately at: togethertolerant@gmail.com\n\n"
                        f"Best regards,\n"
                        f"Tolerance Together Team"
                    )
                )
                if not ok:
                    print("Signup email error: see [MAIL ERROR] log above")


                login_user(new_user, remember=True)
                flash('Registration was successful! Please sign in to join the discussion.', category='success')
                return redirect(url_for('views.home'))

        except Exception as e:
            # Zeig den echten Fehler in der Konsole
            print("Sign-up error:", e)
            flash('There was an error processing the data. Please try again.', category='error')

    return render_template("sign_up.html", user=current_user)

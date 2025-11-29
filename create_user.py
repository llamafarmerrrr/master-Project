#from website import create_app, db
#from website.models import User
#from werkzeug.security import generate_password_hash

#app = create_app()

#with app.app_context():
#    email = "admin@example.com"

   # user = User.query.filter_by(email=email).first()
  #  if user is None:
 #       user = User(
#         #   email=email,
        #    user_name="admin",
       #     first_name="Admin",
      #      family_name="User",
     #       gender="female",
    #        age="25",
   #     )
  #      db.session.add(user)

    # ✅ no 'sha256' here anymore
 #   user.password = generate_password_hash("1234")  # default: pbkdf2:sha256
#
  #  db.session.commit()
 #   print("User ready:", user.id, user.email)
